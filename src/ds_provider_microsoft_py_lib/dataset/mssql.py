"""
**File:** ``mssql.py``
**Region:** ``ds_provider_microsoft_py_lib/dataset/mssql``

MSSQL Table Dataset

This module implements a dataset for Microsoft SQL Server tables.

Example:
>>> dataset = MsSqlTable(
...    linked_service=MsSqlLinkedService(...),
...    settings=MsSqlTableDatasetSettings(
...        table="your_table_name",
...        schema="your_schema_name",
...    )
... )
>>> dataset.read()
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

import pandas as pd
from ds_common_logger_py_lib import Logger
from ds_common_serde_py_lib import Serializable
from ds_resource_plugin_py_lib.common.resource.dataset import (
    DatasetSettings,
    DatasetStorageFormatType,
    TabularDataset,
)
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    DeleteError,
    ListError,
    PurgeError,
    ReadError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError, ValidationError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    asc,
    desc,
    insert,
    quoted_name,
    select,
    text,
)
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.inspection import inspect
from sqlalchemy.sql import Select

from ..enums import ResourceType
from ..linked_service.mssql import MsSqlLinkedService

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class ReadSettings(Serializable):
    """
    Settings specific to the read() operation.

    These settings only apply when reading data from the database
    and do not affect create(), delete(), update(), or rename() operations.
    """

    limit: int | None = None
    """The limit of the data to read."""

    columns: Sequence[str] | None = None
    """
    Specific columns to select. If None, selects all columns (*).

    Example:
        columns=["id", "name", "created_at"]
    """

    filters: dict[str, Any] | None = None
    """
    Dictionary of column filters for WHERE clause. Uses equality comparison.

    Example:
        filters={"status": "active", "amount": 100}

    Multiple filters are combined with AND.
    """

    order_by: Sequence[str | tuple[str, str]] | None = None
    """
    Columns to order by. Can be:
    - List of column names (defaults to ascending)
    - List of (column_name, 'asc'/'desc') tuples

    Example:
        order_by=["created_at"]  # ascending
        order_by=[("created_at", "desc"), "name"]  # created_at desc, name asc
    """


@dataclass(kw_only=True)
class CreateSettings(Serializable):
    """
    Settings specific to the create() operation.

    These settings only apply when writing data to the database
    and do not affect read(), delete(), update(), or rename() operations.
    """

    index: bool = False
    """
    Whether to include the index in the output.
    """

    primary_key: bool = False
    """Whether to create a primary key when creating a new table."""

    primary_key_columns: Sequence[str] | None = None
    """Primary key columns to create when `primary_key` is enabled."""


@dataclass(kw_only=True)
class MsSqlTableDatasetSettings(DatasetSettings):
    table: str
    """Table name for dataset operations."""

    schema: str
    """Schema for dataset operations."""

    read: ReadSettings = field(default_factory=ReadSettings)
    """Settings for read()."""

    create: CreateSettings = field(default_factory=CreateSettings)
    """Settings for create()."""


MsSqlTableDatasetSettingsType = TypeVar(
    "MsSqlTableDatasetSettingsType",
    bound=MsSqlTableDatasetSettings,
)
MsSqlLinkedServiceType = TypeVar(
    "MsSqlLinkedServiceType",
    bound=MsSqlLinkedService[Any],
)


@dataclass(kw_only=True)
class MsSqlTable(
    TabularDataset[
        MsSqlLinkedServiceType,
        MsSqlTableDatasetSettingsType,
        PandasSerializer,
        PandasDeserializer,
    ],
    Generic[MsSqlLinkedServiceType, MsSqlTableDatasetSettingsType],
):
    linked_service: MsSqlLinkedServiceType
    settings: MsSqlTableDatasetSettingsType

    serializer: PandasSerializer | None = field(
        default_factory=lambda: PandasSerializer(format=DatasetStorageFormatType.JSON),
    )
    deserializer: PandasDeserializer | None = field(
        default_factory=lambda: PandasDeserializer(format=DatasetStorageFormatType.JSON),
    )

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the Dataset.

        Returns:
            ResourceType
        """
        return ResourceType.MICROSOFT_SQL_DATASET

    def create(self, **_kwargs: Any) -> None:
        """
        Create/write data to the specified table.

        Writes self.input (pandas DataFrame) to the database table with the
        configured create settings (mode, etc.).

        Args:
            _kwargs: Additional keyword arguments to pass to the request.

        Raises:
            ConnectionError: If the connection fails.
            CreateError: If the create operation fails.
        """
        logger.debug("Starting create operation for %s.%s", self.settings.schema, self.settings.table)
        if self.input is None or self.input.empty:
            logger.debug("Create skipped because input is empty.")
            self.output = self._output_from_empty_input()
            return

        try:
            create_input = self.input.reset_index() if self.settings.create.index else self.input.copy()
            logger.debug(
                "Create input prepared with %d rows and columns=%s",
                len(create_input),
                list(create_input.columns),
            )
            with self.linked_service.connection.begin() as conn:
                table_exists = bool(inspect(conn).has_table(self.settings.table, schema=self.settings.schema))
                logger.debug("Table exists=%s for %s.%s", table_exists, self.settings.schema, self.settings.table)
                if table_exists:
                    table = self._get_table()
                else:
                    logger.debug("Table does not exist; creating new table for create operation.")
                    table = self._build_table_from_input(create_input)
                    table.create(bind=conn)
                self._copy_into_table(conn, table, create_input)
            self.output = self.input.copy()
            self._set_schema(self.output)
            logger.debug("Create completed successfully. Rows written=%d", len(self.output))
        except ValidationError as exc:
            logger.error("Create validation failed: %s", exc.message)
            raise CreateError(
                message=exc.message,
                status_code=exc.status_code,
                details={**(exc.details or {}), "settings": self.settings.create.serialize()},
            ) from exc
        except Exception as exc:
            logger.error("Create failed: %s", exc)
            raise CreateError(
                message=f"Failed to write data to table: {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "settings": self.settings.create.serialize(),
                },
            ) from exc

    def read(self, **_kwargs: Any) -> None:
        """
        Read rows from the configured table into `self.output`.

        Args:
            _kwargs: Additional keyword arguments for interface compatibility.

        Returns:
            None

        Raises:
            ReadError: If reading data fails.
        """
        logger.debug("Starting read operation for %s.%s", self.settings.schema, self.settings.table)
        stmt: Select[Any] | None = None
        try:
            self._validate_read_settings()
            table = self._get_table()
            stmt = self._build_select_columns(table)
            stmt = self._build_filters(stmt, table)
            stmt = self._build_order_by(stmt, table)

            if self.settings.read.limit is not None:
                stmt = stmt.limit(self.settings.read.limit)

            logger.debug("Executing query: %s", stmt)
            with self.linked_service.connection.connect() as conn:
                rows = conn.execute(stmt).mappings().all()
            self.output = pd.DataFrame.from_records(rows)  # type: ignore[type-var]
            logger.debug("Read completed successfully. Rows read=%d", len(self.output))
        except NoSuchTableError as exc:
            logger.error(
                "Table '%s' does not exist in schema '%s'.",
                self.settings.table,
                self.settings.schema,
            )
            raise ReadError(
                message=f"Table '{self.settings.table}' does not exist in schema '{self.settings.schema}'.",
                status_code=404,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "settings": self.settings.read.serialize(),
                },
            ) from exc
        except ValidationError as exc:
            logger.error("Validation error: %s", exc)
            details = {**(exc.details or {}), "settings": self.settings.read.serialize()}
            raise ReadError(
                message=exc.message,
                status_code=exc.status_code,
                details=details,
            ) from exc
        except Exception as exc:
            logger.error("Failed to read data from table: %s", exc)
            raise ReadError(
                message=f"Failed to read data from table: {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "query": str(stmt) if stmt is not None else None,
                    "settings": self.settings.read.serialize(),
                },
            ) from exc

    def purge(self, **_kwargs: Any) -> None:
        """
        Remove all content from the target table.

        Drops the entire table, leaving the structure empty. Per contract,
        the target is empty after purge() returns. This is idempotent --
        purging an already-empty (or non-existent) table is a no-op.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            ConnectionError: If the connection is not established.
            PurgeError: If the purge operation fails.
        """

        try:
            # DROP TABLE IF EXISTS ensures idempotency
            query = (
                f"DROP TABLE IF EXISTS "
                f"{quoted_name(self.settings.schema, quote=True)}."
                f"{quoted_name(self.settings.table, quote=True)};"
            )
            logger.debug(f"Dropping table: {self.settings.schema}.{self.settings.table}")

            with self.linked_service.connection.begin() as conn:
                conn.execute(text(query))

            logger.info(f"Successfully purged table: {self.settings.schema}.{self.settings.table}")
        except Exception as exc:
            logger.error(f"Failed to purge table: {exc}", exc_info=True)
            raise PurgeError(
                message=f"Failed to purge table '{self.settings.schema}.{self.settings.table}': {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                },
            ) from exc

    def delete(self, **_kwargs: Any) -> None:
        """
        Delete specific rows from the target table.

        Removes only the rows in self.input, matched by all columns as identity.
        Per contract: empty input is a no-op (returns immediately).
        Deleting a row that does not exist is not an error.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            ConnectionError: If the connection is not established.
            DeleteError: If the delete operation fails.
        """
        # Per contract: Empty input is not an error, return immediately
        if self.input is None or self.input.empty:
            logger.debug("Empty input provided to delete(); returning without action.")
            self.output = self._output_from_empty_input()
            return

        try:
            # Use all columns present in the input row as match criteria
            key_columns = list(self.input.columns)

            # Map potentially unsafe column names to safe SQLAlchemy bind parameter names
            param_map = {col: f"p{idx}" for idx, col in enumerate(key_columns)}
            where_clause = " AND ".join(f"{self._quote_identifier(col)} = :{param_map[col]}" for col in key_columns)
            # Note: This is safe from SQL injection because:
            # 1. Schema and table names are quoted with quoted_name()
            # 2. Column names are validated through _quote_identifier() which rejects unsafe characters
            # 3. Values are passed as parameters, not interpolated into the SQL
            if getattr(self.settings, "schema", None):
                table_identifier = (
                    f"{quoted_name(self.settings.schema, quote=True)}.{quoted_name(self.settings.table, quote=True)}"
                )
            else:
                table_identifier = f"{quoted_name(self.settings.table, quote=True)}"
            delete_sql = text(f"DELETE FROM {table_identifier} WHERE {where_clause}")  # nosec B608

            # Build payloads using the safe parameter names
            records = self.input.to_dict(orient="records")
            payloads = [{param_map[col]: row[col] for col in key_columns} for row in records]

            with self.linked_service.connection.begin() as conn:
                conn.execute(delete_sql, payloads)

            # Per contract: Populate output with the affected rows (copy of input)
            self.output = self.input.copy()
            self._set_schema(self.output)
            logger.info(f"Successfully deleted {len(payloads)} rows from {self.settings.schema}.{self.settings.table}")
        except Exception as exc:
            logger.error(f"Failed to delete rows from table: {exc}", exc_info=True)
            raise DeleteError(
                message=f"Failed to delete rows from table '{self.settings.schema}.{self.settings.table}': {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "row_count": len(self.input),
                },
            ) from exc

    def update(self, **_kwargs: Any) -> None:
        """
        Update existing rows in the target table.

        This operation is not supported for SQL Server datasets at this time.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            NotSupportedError: Always -- update is not supported.
        """
        raise NotSupportedError(
            message="Update operation is not supported for SQL Server datasets.",
            details={"table": self.settings.table, "schema": self.settings.schema},
        )

    def rename(self, **_kwargs: Any) -> None:
        """
        Rename a resource (table) in the backend.

        This operation is not supported for SQL Server datasets at this time.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            NotSupportedError: Always -- rename is not supported.
        """
        raise NotSupportedError(
            message="Rename operation is not supported for SQL Server datasets.",
            details={"table": self.settings.table, "schema": self.settings.schema},
        )

    def close(self) -> None:
        """
        Clean up the connection to the backend.

        Per contract: must be safe to call multiple times and never raise.

        Returns:
            None
        """
        try:
            self.linked_service.close()
        except Exception:
            logger.debug("Exception suppressed during close().", exc_info=True)

    def list(self, **_kwargs: Any) -> None:
        """
        Discover available resources (tables) in the schema.

        Uses SQLAlchemy's Inspector to reflect and retrieve all tables
        in the configured schema with their metadata (type: table or view).

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            ConnectionError: If the connection is not established.
            ListError: If the list operation fails.
        """
        try:
            inspector = inspect(self.linked_service.connection)

            # Get all tables and views in the schema
            table_names = sorted(inspector.get_table_names(schema=self.settings.schema))
            view_names = sorted(inspector.get_view_names(schema=self.settings.schema))

            # Build resource info list with metadata
            tables_info = []
            for table_name in table_names:
                tables_info.append(
                    {
                        "TABLE_SCHEMA": self.settings.schema,
                        "TABLE_NAME": table_name,
                        "TABLE_TYPE": "BASE TABLE",
                    }
                )
            for view_name in view_names:
                tables_info.append(
                    {
                        "TABLE_SCHEMA": self.settings.schema,
                        "TABLE_NAME": view_name,
                        "TABLE_TYPE": "VIEW",
                    }
                )

            # Per contract: self.output must be populated with discovered resources
            self.output = pd.DataFrame(tables_info)
            self._set_schema(self.output)
            logger.info(f"Successfully listed {len(self.output)} tables in schema: {self.settings.schema}")
        except ListError:
            # Re-raise our own exception type
            raise
        except Exception as exc:
            logger.error(f"Failed to list tables in schema: {exc}", exc_info=True)
            raise ListError(
                message=f"Failed to list tables in schema '{self.settings.schema}': {exc!s}",
                status_code=500,
                details={"schema": self.settings.schema},
            ) from exc

    def upsert(self, **_kwargs: Any) -> None:
        """
        Insert or update rows in the target table.

        This operation is not supported for SQL Server datasets at this time.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            NotSupportedError: Always -- upsert is not supported.
        """
        raise NotSupportedError(
            message="Upsert operation is not supported for SQL Server datasets.",
            details={"table": self.settings.table, "schema": self.settings.schema},
        )

    def _set_schema(self, content: pd.DataFrame) -> None:
        """
        Set the schema from the content.

        Args:
            content: The content to set the schema from.
        """
        converted = content.convert_dtypes(dtype_backend="pyarrow")
        self.schema = {str(col): str(dtype) for col, dtype in converted.dtypes.to_dict().items()}

    def _get_table(self) -> Table:
        """
        Get the SQLAlchemy Table object for the configured schema and table.

        Returns:
            Table: The SQLAlchemy Table object.
        """
        schema_name = quoted_name(self.settings.schema, quote=True)
        table_name = quoted_name(self.settings.table, quote=True)

        metadata = MetaData(schema=schema_name)

        return Table(
            table_name,
            metadata,
            schema=schema_name,
            autoload_with=self.linked_service.connection,
        )

    @staticmethod
    def _pandas_dtype_to_sqlalchemy(dtypes: pd.Series) -> dict[str, Any]:
        """
        Convert pandas dtypes Series to a dict mapping column names to SQLAlchemy types.

        Args:
            dtypes: Pandas Series where index is column names and values are dtypes.

        Returns:
            dict[str, Any]: Dictionary mapping column names to SQLAlchemy types.
        """
        dtype_map: dict[str, Any] = {}

        for col_name, dtype in dtypes.items():
            col_name_str = str(col_name)

            if pd.api.types.is_integer_dtype(dtype):
                if hasattr(dtype, "itemsize") and dtype.itemsize <= 2:
                    dtype_map[col_name_str] = Integer()
                else:
                    dtype_map[col_name_str] = BigInteger()
            elif pd.api.types.is_float_dtype(dtype):
                dtype_map[col_name_str] = Float()
            elif pd.api.types.is_bool_dtype(dtype):
                dtype_map[col_name_str] = Boolean()
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                dtype_map[col_name_str] = DateTime()
            elif pd.api.types.is_string_dtype(dtype) or isinstance(dtype, pd.CategoricalDtype):
                dtype_map[col_name_str] = String(length=255)
            else:
                dtype_map[col_name_str] = String(length=255)

        return dtype_map

    def _validate_column(self, table: Table, column_name: str) -> None:
        """
        Validate that a column exists in the table.

        Args:
            table: The SQLAlchemy Table object.
            column_name: The name of the column to validate.

        Raises:
            ValueError: If the column doesn't exist in the table.
        """
        if column_name not in table.c:
            available_columns = list(table.c.keys())
            raise ValueError(
                f"Column '{column_name}' not found in table '{self.settings.table}'. Available columns: {available_columns}"
            )

    def _validate_columns(self, table: Table, column_names: Sequence[str]) -> None:
        """
        Validate that all requested columns exist in the reflected table.

        Args:
            table: Reflected SQLAlchemy table.
            column_names: Column names to validate.

        Returns:
            None

        Raises:
            ValidationError: If one or more columns do not exist in the table.
        """
        available_columns = list(table.c.keys())
        missing_columns = list(dict.fromkeys(col for col in column_names if col not in table.c))
        if missing_columns:
            raise ValidationError(
                message=f"Column(s) not found in table '{self.settings.table}'.",
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "missing_columns": missing_columns,
                    "available_columns": available_columns,
                },
            )

    def _build_select_columns(self, table: Table) -> Select[Any]:
        """
        Build a SELECT statement for configured columns or all columns.

        Args:
            table: Reflected SQLAlchemy table.

        Returns:
            Select[Any]: SELECT statement with chosen columns.

        Raises:
            ValidationError: If any selected column does not exist.
        """
        if self.settings.read.columns:
            self._validate_columns(table, self.settings.read.columns)

            selected_columns = [table.c[col_name] for col_name in self.settings.read.columns]
            return select(*selected_columns)

        return select(table)

    def _build_filters(self, stmt: Select[Any], table: Table) -> Select[Any]:
        """
        Apply equality filters from read settings to the SELECT statement.

        Args:
            stmt: Current SELECT statement.
            table: Reflected SQLAlchemy table.

        Returns:
            Select[Any]: SELECT statement with WHERE conditions applied.

        Raises:
            ValidationError: If any filter column does not exist.
        """
        if not self.settings.read.filters:
            return stmt

        self._validate_columns(table, list(self.settings.read.filters.keys()))

        filter_conditions = [table.c[col_name] == value for col_name, value in self.settings.read.filters.items()]

        return stmt.where(and_(*filter_conditions))

    def _build_order_by(self, stmt: Select[Any], table: Table) -> Select[Any]:
        """
        Apply ORDER BY clauses from read settings to the SELECT statement.

        Args:
            stmt: Current SELECT statement.
            table: Reflected SQLAlchemy table.

        Returns:
            Select[Any]: SELECT statement with ORDER BY applied.

        Raises:
            ValidationError: If any order-by column does not exist.
        """
        if not self.settings.read.order_by:
            return stmt

        order_columns = [
            col_name if isinstance(order_spec, tuple) else order_spec
            for order_spec in self.settings.read.order_by
            for col_name in ([order_spec[0]] if isinstance(order_spec, tuple) else [order_spec])
        ]
        self._validate_columns(table, order_columns)

        order_clauses = []
        for order_spec in self.settings.read.order_by:
            if isinstance(order_spec, tuple):
                col_name, direction = order_spec

                col = table.c[col_name]
                if direction.lower() == "desc":
                    order_clauses.append(desc(col))
                else:
                    order_clauses.append(asc(col))
            else:
                order_clauses.append(asc(table.c[order_spec]))

        return stmt.order_by(*order_clauses)

    def _quote_identifier(self, name: str) -> str:
        """
        Quote identifiers safely for SQL Server using SQLAlchemy's identifier preparer.

        Reject identifiers containing obvious injection primitives like quotes, semicolons,
        or brackets before quoting.

        Args:
            name: The identifier name to quote.

        Returns:
            str: The safely quoted identifier.

        Raises:
            ValueError: If the identifier contains unsafe characters.
        """
        if re.search(r"[;\"'\[\]]", name):
            raise ValueError(f"Unsafe identifier: {name!r}")
        preparer = self.linked_service.connection.dialect.identifier_preparer
        return preparer.quote(name)

    def get_details(self) -> dict[str, Any]:
        """
        Get details about the dataset.

        Constructs and returns a dictionary containing metadata about the current
        dataset configuration, including table name, schema name, and optional
        query filters and delete settings.

        Returns:
            dict[str, Any]: A dictionary containing:
                - table_name (str): The name of the target table
                - schema_name (str): The schema containing the table
                - query_filter (Any, optional): Filter criteria if specified
                - delete_table (str, optional): Delete table setting if specified
        """
        details: dict[str, Any] = {
            "table_name": self.settings.table,
            "schema_name": self.settings.schema,
        }

        read_settings = getattr(self.settings, "read", None)
        if read_settings is not None and read_settings.filters is not None:
            details["filters"] = read_settings.filters

        delete_settings = getattr(self.settings, "delete", None)
        if delete_settings is not None:
            details["delete_table"] = str(delete_settings.delete_table)

        return details

    def _copy_into_table(self, conn: Any, table: Table, content: pd.DataFrame) -> None:
        """
        Insert rows into SQL Server table using raw SQL for proper transaction handling.

        Args:
            conn: SQLAlchemy connection object.
            table: SQLAlchemy Table object (metadata only).
            content: DataFrame containing rows to insert.
        """
        if content.empty:
            return

        logger.debug(f"Inserting {len(content)} rows into {self.settings.schema}.{self.settings.table}")

        # Check if any columns are identity columns and if input includes them
        identity_columns = [col.name for col in table.columns if hasattr(col, "identity") and col.identity]
        has_identity_in_input = any(col in content.columns for col in identity_columns)

        try:
            # Enable IDENTITY_INSERT if table has identity columns and input includes them
            if identity_columns and has_identity_in_input:
                table_ref = f"[{self.settings.schema}].[{self.settings.table}]"
                enable_sql = f"SET IDENTITY_INSERT {table_ref} ON"
                logger.debug(f"Enabling IDENTITY_INSERT for {self.settings.schema}.{self.settings.table}")
                conn.execute(text(enable_sql))

            stmt = insert(table)
            records = content.to_dict(orient="records")

            # Execute insert with all records at once
            conn.execute(stmt, records)

        finally:
            # Always disable IDENTITY_INSERT if it was enabled
            if identity_columns and has_identity_in_input:
                table_ref = f"[{self.settings.schema}].[{self.settings.table}]"
                disable_sql = f"SET IDENTITY_INSERT {table_ref} OFF"
                logger.debug(f"Disabling IDENTITY_INSERT for {self.settings.schema}.{self.settings.table}")
                conn.execute(text(disable_sql))

    def _resolve_create_primary_key_columns(
        self,
        content: pd.DataFrame,
    ) -> Sequence[str] | None:
        """
        Resolve and validate create-time primary key columns.

        Args:
            content: Input DataFrame used for table creation.

        Returns:
            Sequence[str] | None: Primary key columns for new table creation.

        Raises:
            ValidationError: If `primary_key` is enabled but columns are invalid.
        """
        if not self.settings.create.primary_key:
            logger.debug("Create primary key disabled in settings.")
            return None

        if not self.settings.create.primary_key_columns:
            logger.error("Create primary key is enabled but primary_key_columns is missing.")
            raise ValidationError(
                message="Missing primary key columns for create().",
                status_code=400,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "create_settings": self.settings.create.serialize(),
                },
            )

        missing_columns = [col for col in self.settings.create.primary_key_columns if col not in content.columns]
        if missing_columns:
            logger.error("Create primary key columns missing from input: %s", missing_columns)
            raise ValidationError(
                message="Primary key columns do not exist in create input.",
                status_code=400,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "missing_columns": missing_columns,
                    "primary_key_columns": list(self.settings.create.primary_key_columns),
                },
            )

        logger.debug("Resolved create primary key columns: %s", list(self.settings.create.primary_key_columns))
        return list(self.settings.create.primary_key_columns)

    def _build_table_from_input(
        self,
        content: pd.DataFrame,
    ) -> Table:
        """
        Build a SQLAlchemy Table definition from input DataFrame dtypes.

        Args:
            content: Input DataFrame to build the table from.

        Returns:
            Table: SQLAlchemy Table definition.
        """
        schema_name = quoted_name(self.settings.schema, quote=True)
        table_name = quoted_name(self.settings.table, quote=True)
        metadata = MetaData(schema=schema_name)
        dtype_map = self._pandas_dtype_to_sqlalchemy(content.dtypes)
        primary_key_columns = self._resolve_create_primary_key_columns(content)
        primary_key_set = set(primary_key_columns or [])
        logger.debug(
            "Building table from input with columns=%s and primary_key_columns=%s",
            list(content.columns),
            list(primary_key_set),
        )
        columns = [
            Column(
                str(col_name),
                cast("Any", dtype_map[str(col_name)]),
                primary_key=str(col_name) in primary_key_set,
                nullable=str(col_name) not in primary_key_set,
            )
            for col_name in content.columns
        ]
        return Table(
            table_name,
            metadata,
            *columns,
            schema=schema_name,
        )

    def _output_from_empty_input(self) -> pd.DataFrame:
        """
        Build a consistent empty-operation output while preserving input schema.

        Returns:
            pd.DataFrame: Empty dataframe or a schema-preserving input copy.
        """
        input_value = cast("Any", self.input)
        if input_value is None:
            return pd.DataFrame()
        return cast("pd.DataFrame", input_value.copy())

    def _validate_read_settings(self) -> None:
        """
        Validate read settings before query construction.

        Returns:
            None

        Raises:
            ValidationError: If limit or order direction is invalid.
        """
        read_settings = self.settings.read

        if read_settings.limit is not None and read_settings.limit <= 0:
            raise ValidationError(
                message="Read limit must be greater than 0.",
                status_code=400,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "limit": read_settings.limit,
                },
            )

        if not read_settings.order_by:
            return

        invalid_order_specs: list[dict[str, str]] = []
        for order_spec in read_settings.order_by:
            if not isinstance(order_spec, tuple):
                continue

            col_name, direction = order_spec
            if direction.lower() not in {"asc", "desc"}:
                invalid_order_specs.append(
                    {
                        "column": col_name,
                        "direction": direction,
                    }
                )

        if invalid_order_specs:
            raise ValidationError(
                message="Invalid order_by direction. Use 'asc' or 'desc'.",
                status_code=400,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "invalid_order_by": invalid_order_specs,
                },
            )
