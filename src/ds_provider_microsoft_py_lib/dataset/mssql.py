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
...        delete=DeleteSettings(delete_table=False)
...    )
... )
>>> dataset.read()
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, cast

import pandas as pd
from ds_common_logger_py_lib import Logger
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
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import ConnectionError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    asc,
    desc,
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
class ReadSettings:
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
class CreateSettings:
    """
    Settings specific to the create() operation.

    These settings only apply when writing data to the database
    and do not affect read(), delete(), update(), or rename() operations.
    """

    mode: Literal["fail", "append", "replace"] = "fail"
    """
    Write mode for the data.

    Options:
    - "fail": Raise an error if the table already exists.
    - "append": Insert new rows (default). Creates table if it doesn't exist.
    - "replace": Drop table if exists, recreate, then insert.
    """

    index: bool = False
    """
    Whether to include the index in the output.
    """


@dataclass(kw_only=True)
class MsSqlTableDatasetSettings(DatasetSettings):
    table: str
    schema: str
    read: ReadSettings | None = None
    create: CreateSettings | None = None


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
        # Per contract: Empty input is not an error, return immediately
        if self.input is None or self.input.empty:
            logger.debug("Empty input provided to create(); returning without action.")
            return

        create_props = self.settings.create or CreateSettings()

        if self.linked_service.connection is None:
            raise ConnectionError(message="Connection pool is not initialized.")

        if self.input is None or self.input.empty:
            raise CreateError(
                message="Input is empty or None.",
                status_code=400,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "settings": self.settings.create,
                },
            )

        try:
            self.input.to_sql(
                name=self.settings.table,
                con=self.linked_service.connection,
                schema=self.settings.schema,
                if_exists=create_props.mode,
                index=create_props.index,
                dtype=cast("Any", self._pandas_dtype_to_sqlalchemy(self.input.dtypes)),
            )
            # Per contract: Populate output with the affected rows (copy of input)
            self.output = self.input.copy()
            self._set_schema(self.output)
            logger.info(f"Successfully created/inserted {len(self.output)} rows to {self.settings.schema}.{self.settings.table}")
        except Exception as exc:
            logger.error(f"Failed to write data to table: {exc}", exc_info=True)
            raise CreateError(
                message=f"Failed to write data to table '{self.settings.schema}.{self.settings.table}': {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "row_count": len(self.input),
                },
            ) from exc

    def read(self, **_kwargs: Any) -> None:
        """
        Read data from the specified table.

        Reads data from the configured table using optional filters,
        column selection, and ordering.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            ConnectionError: If the connection is not established.
            ReadError: If the read operation fails.
        """
        if self.linked_service.connection is None:
            raise ConnectionError(message="Connection pool is not initialized.")

        try:
            table = self._get_table()
        except NoSuchTableError as exc:
            raise ReadError(
                message=f"Table '{self.settings.schema}.{self.settings.table}' does not exist.",
                status_code=404,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                },
            ) from exc

        read_props = self.settings.read

        stmt = self._build_select_columns(table, read_props)
        stmt = self._build_filters(stmt, table, read_props)
        stmt = self._build_order_by(stmt, table, read_props)

        if read_props and read_props.limit is not None:
            stmt = stmt.limit(read_props.limit)

        logger.debug(f"Executing read query: {stmt}")
        try:
            chunks = pd.read_sql(
                stmt,
                con=self.linked_service.connection,
                chunksize=100_000,
                dtype_backend="pyarrow",
            )
            self.output = pd.concat(list(chunks), ignore_index=True)
            self._set_schema(self.output)
            logger.info(f"Successfully read {len(self.output)} rows from {self.settings.schema}.{self.settings.table}")
        except Exception as exc:
            logger.error(f"Failed to read data from table: {exc}", exc_info=True)
            raise ReadError(
                message=f"Failed to read data from table '{self.settings.schema}.{self.settings.table}': {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
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
            query = f"DROP TABLE IF EXISTS {quoted_name(self.settings.table, quote=True)};"
            logger.debug(f"Dropping table: {self.settings.schema}.{self.settings.table}")

            with self.linked_service.connection.connect() as conn:
                conn.execute(text(query))
                conn.commit()

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
            return

        try:
            # Use all columns present in the input row as match criteria
            key_columns = list(self.input.columns)

            # Map potentially unsafe column names to safe SQLAlchemy bind parameter names
            param_map = {col: f"p{idx}" for idx, col in enumerate(key_columns)}
            where_clause = " AND ".join(f"{self._quote_identifier(col)} = :{param_map[col]}" for col in key_columns)
            # Note: This is safe from SQL injection because:
            # 1. Table name is quoted with quoted_name()
            # 2. Column names are validated through _quote_identifier() which rejects unsafe characters
            # 3. Values are passed as parameters, not interpolated into the SQL
            delete_sql = text(f"DELETE FROM {quoted_name(self.settings.table, quote=True)} WHERE {where_clause}")  # nosec B608

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
        self.linked_service.close()

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

            # Get all tables in the schema, sorted alphabetically
            table_names = sorted(inspector.get_table_names(schema=self.settings.schema))
            view_names = set(inspector.get_view_names(schema=self.settings.schema))

            # Build table info list with metadata
            tables_info = []
            for table_name in table_names:
                table_type = "VIEW" if table_name in view_names else "BASE TABLE"
                tables_info.append(
                    {
                        "TABLE_SCHEMA": self.settings.schema,
                        "TABLE_NAME": table_name,
                        "TABLE_TYPE": table_type,
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

    def _pandas_dtype_to_sqlalchemy(self, dtypes: pd.Series) -> dict[str, Any]:
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

    def _build_select_columns(self, table: Table, read_props: ReadSettings | None) -> Select[Any]:
        """
        Build the SELECT clause of the query.

        Args:
            table: The SQLAlchemy Table object.
            read_props: Read-specific settings.

        Returns:
            Select: The SELECT statement with specified columns or all columns.

        Raises:
            ValueError: If any specified column doesn't exist in the table.
        """
        if read_props and read_props.columns:
            for col_name in read_props.columns:
                self._validate_column(table, col_name)

            selected_columns = [table.c[col_name] for col_name in read_props.columns]
            return select(*selected_columns)

        return select(table)

    def _build_filters(self, stmt: Select[Any], table: Table, read_props: ReadSettings | None) -> Select[Any]:
        """
        Build the WHERE clause of the query from filters.

        Args:
            stmt: The current SELECT statement.
            table: The SQLAlchemy Table object.
            read_props: Read-specific settings.

        Returns:
            Select: The SELECT statement with WHERE clause applied.

        Raises:
            ValueError: If any filter column doesn't exist in the table.
        """
        if not read_props or not read_props.filters:
            return stmt

        for col_name in read_props.filters:
            self._validate_column(table, col_name)

        filter_conditions = [table.c[col_name] == value for col_name, value in read_props.filters.items()]

        return stmt.where(and_(*filter_conditions))

    def _build_order_by(self, stmt: Select[Any], table: Table, read_props: ReadSettings | None) -> Select[Any]:
        """
        Build the ORDER BY clause of the query.

        Args:
            stmt: The current SELECT statement.
            table: The SQLAlchemy Table object.
            read_props: Read-specific settings.

        Returns:
            Select: The SELECT statement with ORDER BY clause applied.

        Raises:
            ValueError: If any order_by column doesn't exist in the table.
        """
        if not read_props or not read_props.order_by:
            return stmt

        order_clauses = []
        for order_spec in read_props.order_by:
            if isinstance(order_spec, tuple):
                col_name, direction = order_spec
                self._validate_column(table, col_name)

                col = table.c[col_name]
                if direction.lower() == "desc":
                    order_clauses.append(desc(col))
                else:
                    order_clauses.append(asc(col))
            else:
                self._validate_column(table, order_spec)
                order_clauses.append(asc(table.c[order_spec]))

        return stmt.order_by(*order_clauses)

    def _quote_identifier(self, name: str) -> str:
        """
        Quote identifiers safely for SQL Server using SQLAlchemy's identifier preparer.

        Reject identifiers containing obvious injection primitives like quotes, semicolons,
        or brackets before quoting.

        Returns:
            str: The safely quoted identifier.
        """
        if re.search(r"[;\"'\[\]]", name):
            raise ValueError(f"Unsafe identifier: {name!r}")
        preparer = self.linked_service.connection.dialect.identifier_preparer
        return preparer.quote(name)

    def get_details(self) -> dict[str, Any]:
        """
        Get details about the dataset.

        Returns:
            dict[str, Any]
        """
        details: dict[str, Any] = {
            "table_name": self.settings.table,
            "schema_name": self.settings.schema,
        }

        read_settings = getattr(self.settings, "read", None)
        if read_settings is not None and read_settings.query_filter is not None:
            details["query_filter"] = read_settings.query_filter

        delete_settings = getattr(self.settings, "delete", None)
        if delete_settings is not None:
            details["delete_table"] = str(delete_settings.delete_table)

        return details
