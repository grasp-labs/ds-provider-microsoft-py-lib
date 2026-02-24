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
from typing import Any, Generic, Literal, NoReturn, TypeVar, cast

import pandas as pd
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.dataset import (
    DatasetSettings,
    DatasetStorageFormatType,
    TabularDataset,
)
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError, DeleteError, ReadError
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
            self.output = self.input
            self._set_schema(self.input)
        except Exception as exc:
            raise CreateError(
                message=f"Failed to write data to table: {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "settings": create_props,
                },
            ) from exc

    def read(self, **_kwargs: Any) -> None:
        """
        Read data from the specified endpoint.

        Args:
            _kwargs: Additional keyword arguments to pass to the request.

        Raises:
            ConnectionError: If the connection fails.
            ValueError: If specified columns, filters, or order_by columns don't exist.
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

        logger.debug(f"Executing query: {stmt}")
        try:
            chunks = pd.read_sql(
                stmt,
                con=self.linked_service.connection,
                chunksize=100_000,
                dtype_backend="pyarrow",
            )
            self.output = pd.concat(list(chunks), ignore_index=True)
            self._set_schema(self.output)
        except Exception as exc:
            raise ReadError(
                message=f"Failed to read data from table: {exc!s}",
                status_code=500,
                details={
                    "table": self.settings.table,
                    "schema": self.settings.schema,
                    "query": stmt,
                    "settings": read_props,
                },
            ) from exc

    def purge(self, **_kwargs: Any) -> None:
        if self.linked_service.connection is None:
            raise ConnectionError(message="Connection pool is not initialized.")

        try:
            query = f"DROP TABLE IF EXISTS {quoted_name(self.settings.table, quote=True)};"
            logger.debug(f"Dropping table: {quoted_name(self.settings.table, quote=True)}")

            with self.linked_service.connection.connect() as conn:
                conn.execute(text(query))
                conn.commit()

            logger.info(f"Successfully dropped table: {quoted_name(self.settings.table, quote=True)}")
        except Exception as exc:
            logger.error(f"Failed to delete table: {exc}", exc_info=True)
            raise DeleteError(f"Failed to delete table: {exc!s}", details=self.get_details(), status_code=500) from exc

    def delete(self, **_kwargs: Any) -> None:
        """
        Delete rows matching the provided input using a WHERE clause.

        Args:
            _kwargs: Additional keyword arguments.

        Returns:
            None

        Raises:
            DeleteError: If there is an error during deletion or if no input rows are provided when delete_table is False.
        """
        if self.input is None or getattr(self.input, "empty", True):
            raise DeleteError("No input rows provided; refusing to delete all rows", details=self.get_details(), status_code=400)

        df = self.input

        # Use all columns present in the input row as match criteria
        key_columns = list(df.columns)
        # Map potentially unsafe column names to safe SQLAlchemy bind parameter names
        param_map = {col: f"p{idx}" for idx, col in enumerate(key_columns)}
        where_clause = " AND ".join(f"{self._quote_identifier(col)} = :{param_map[col]}" for col in key_columns)
        delete_sql = text(f"DELETE FROM {quoted_name(self.settings.table, quote=True)} WHERE {where_clause}")  # nosec B608

        # Build payloads using the safe parameter names
        records = df.to_dict(orient="records")
        payloads = [{param_map[col]: row[col] for col in key_columns} for row in records]
        if self.linked_service.connection is None:
            raise ConnectionError(message="Connection pool is not initialized.")
        try:
            with self.linked_service.connection.begin() as conn:
                conn.execute(delete_sql, payloads)
            logger.info(f"Successfully deleted {len(payloads)} rows from table: {quoted_name(self.settings.table, quote=True)}")
        except Exception as exc:
            logger.error(f"Failed to delete specific rows from table: {exc}", exc_info=True)
            raise DeleteError(
                f"Failed to delete specific rows from table: {exc!s}", details=self.get_details(), status_code=500
            ) from exc

    def update(self, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("Update operation is not supported for PostgreSQL datasets")

    def rename(self, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("Rename operation is not supported for PostgreSQL datasets")

    def close(self) -> None:
        """
        Close the dataset.
        """
        self.linked_service.close()

    def list(self, **_kwargs: Any) -> None:
        """
        List all tables in the specified schema.

        Uses SQLAlchemy's Inspector to reflect and retrieve all tables
        in the configured schema.

        Args:
            _kwargs: Additional keyword arguments (ignored).

        Raises:
            ConnectionError: If the connection fails.
            ReadError: If the list operation fails.

        Returns:
            None (Sets self.output to a DataFrame with table information)
        """
        try:
            # Get the connection (will raise ConnectionError if not connected)
            connection = self.linked_service.connection
        except ConnectionError as exc:
            logger.error(f"Connection not established: {exc}", exc_info=True)
            raise ReadError(
                message=f"Failed to list tables: {exc.message}",
                status_code=500,
                details={"schema": self.settings.schema},
            ) from exc

        try:
            inspector = inspect(connection)

            table_names = sorted(inspector.get_table_names(schema=self.settings.schema))

            tables_info = []
            for table_name in table_names:
                is_view = table_name in inspector.get_view_names(schema=self.settings.schema)
                table_type = "VIEW" if is_view else "BASE TABLE"

                tables_info.append(
                    {
                        "TABLE_SCHEMA": self.settings.schema,
                        "TABLE_NAME": table_name,
                        "TABLE_TYPE": table_type,
                    }
                )

            self.output = pd.DataFrame(tables_info)
            self._set_schema(self.output)
            logger.info(f"Successfully listed {len(self.output)} tables in schema: {self.settings.schema}")
        except Exception as exc:
            logger.error(f"Failed to list tables in schema: {exc}", exc_info=True)
            raise ReadError(
                message=f"Failed to list tables in schema '{self.settings.schema}': {exc!s}",
                status_code=500,
                details={"schema": self.settings.schema},
            ) from exc

    def upsert(self) -> None:
        raise NotImplementedError("Upsert operation is not supported for PostgreSQL datasets")

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
        """Quote identifiers safely for SQL Server using SQLAlchemy's identifier preparer.

        Reject identifiers containing obvious injection primitives like quotes, semicolons,
        or brackets before quoting.

        Returns:
            str: The safely quoted identifier.
        """
        if re.search(r"[;\"'\[\]]", name):
            raise ValueError(f"Unsafe identifier: {name!r}")
        if self.linked_service.connection is None:
            raise ConnectionError(message="Connection pool is not initialized.")
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
