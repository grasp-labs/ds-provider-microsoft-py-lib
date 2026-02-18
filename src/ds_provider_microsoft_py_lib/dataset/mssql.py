import re
import time
from dataclasses import dataclass, field
from typing import Any, Generic, NoReturn, TypeVar

import pandas as pd
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.dataset import (
    DatasetSettings,
    TabularDataset,
)
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError, DeleteError, ReadError
from sqlalchemy import inspect, text

from ..enums import ResourceType
from ..linked_service.mssql import MssqlLinkedService
from ..serde.table import MssqlTableDeserializer, MssqlTableSerializer

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class DeleteSettings:
    """
    Settings specific to the delete() operation.

    These settings only apply when deleting data from the database
    and do not affect other operations like:  create(), read(), update(), or rename().
    """

    delete_table: bool = False
    """
    If True, the entire table will be deleted when delete() is called.
    If False, only the entities specified in the input will be deleted.
    """


@dataclass(kw_only=True)
class MssqlTableDatasetSettings(DatasetSettings):
    table_name: str
    schema_name: str = "dbo"
    chunksize: int | None = 1000  # Rows per batch (recommended for SQL Server)
    delete: DeleteSettings = field(default_factory=DeleteSettings)


MssqlTableDatasetSettingsType = TypeVar(
    "MssqlTableDatasetSettingsType",
    bound=MssqlTableDatasetSettings,
)
MssqlLinkedServiceType = TypeVar(
    "MssqlLinkedServiceType",
    bound=MssqlLinkedService[Any],
)


@dataclass(kw_only=True)
class MssqlTable(
    TabularDataset[
        MssqlLinkedServiceType,
        MssqlTableDatasetSettingsType,
        MssqlTableSerializer,
        MssqlTableDeserializer,
    ],
    Generic[MssqlLinkedServiceType, MssqlTableDatasetSettingsType],
):
    linked_service: MssqlLinkedServiceType
    settings: MssqlTableDatasetSettingsType

    serializer: MssqlTableSerializer = field(
        default_factory=MssqlTableSerializer,
    )
    deserializer: MssqlTableDeserializer = field(
        default_factory=MssqlTableDeserializer,
    )

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the Dataset.

        Returns:
            ResourceType
        """
        return ResourceType.MICROSOFT_SQL_DATASET

    def _get_full_table_name(self) -> str:
        """
        Get the fully qualified table name.

        Returns:
             Schema.Table format
        """
        return f"{self.settings.schema_name}.{self.settings.table_name}"

    def _quote_identifier(self, name: str) -> str:
        """Quote identifiers safely for SQL Server using SQLAlchemy's identifier preparer.

        Reject identifiers containing obvious injection primitives like quotes, semicolons,
        or brackets before quoting.

        Returns:
            str: The safely quoted identifier.
        """
        if re.search(r"[;\"'\[\]]", name):
            raise ValueError(f"Unsafe identifier: {name!r}")
        preparer = self.linked_service.engine.dialect.identifier_preparer
        return preparer.quote(name)

    def _qualified_table(self) -> str:
        """
        Return a safely quoted schema-qualified table name.

        Returns:
                str: The safely quoted schema-qualified table name.
        """

        schema = self._quote_identifier(self.settings.schema_name)
        table = self._quote_identifier(self.settings.table_name)
        return f"{schema}.{table}"

    def read(self, **_kwargs: Any) -> None:
        """
        Read data from SQL Server table.

        Args:
          _kwargs: Additional keyword arguments.

        Returns:
              None

        Raises:
            ReadError: If the table does not exist or if there is an error during reading.
        """
        table_name = self._get_full_table_name()
        logger.debug(f"Reading from table: {table_name}")
        try:
            self.output = pd.read_sql_table(
                table_name=self.settings.table_name,
                con=self.linked_service.engine,
                schema=self.settings.schema_name,
                **_kwargs,
            )
            logger.info(f"Read {len(self.output)} rows from MSSQL")
        except ValueError as exc:
            # pandas raises ValueError when the table does not exist
            raise ReadError(f"Table {table_name} not found in schema {self.settings.schema_name}", status_code=404) from exc
        except Exception as exc:
            logger.error(f"Failed to read from MSSQL: {exc}", exc_info=True)
            raise ReadError(f"Failed to read from MSSQL: {exc!s}") from exc

    def create(self, **_kwargs: Any) -> None:
        """
        Write data to SQL Server table.
        Appends data to existing table (like ADF copy activity).

        Args:
          _kwargs: Additional keyword arguments.

        Returns:
              None

        Raises:
            CreateError: If there is an error during writing to the database.
        """
        try:
            _kwargs.pop("batch_size", None)

            table_name = self._get_full_table_name()
            df = self.input
            row_count, col_count = df.shape
            chunk_size = self.settings.chunksize

            df_clean, rows = self.serializer(df)
            self._log_write_start(table_name, row_count, col_count, chunk_size)

            start_time = time.time()

            # Check if table exists first
            inspector = inspect(self.linked_service.engine)
            table_exists = inspector.has_table(
                self.settings.table_name,
                schema=self.settings.schema_name,
            )
            logger.info(f"Table exists: {table_exists}")

            if not table_exists:
                logger.info("Table does not exist; creating it with inferred types via pandas to_sql")
                # Create empty table with inferred schema so bulk insert can target it
                df_clean.head(0).to_sql(
                    name=self.settings.table_name,
                    con=self.linked_service.engine,
                    schema=self.settings.schema_name,
                    if_exists="fail",
                    index=False,
                )
                logger.info("Table created")

            logger.info("Using fast_executemany for bulk insert...")

            # Get raw pyodbc connection for fast_executemany
            fast_path_succeeded = False
            try:
                raw_conn = self.linked_service.engine.raw_connection()
                try:
                    cursor = raw_conn.cursor()
                    cursor.fast_executemany = True  # type: ignore[attr-defined] # Enable fast bulk insert

                    # Build INSERT statement
                    columns = ", ".join([self._quote_identifier(col) for col in df_clean.columns])
                    placeholders = ", ".join(["?" for _ in df_clean.columns])
                    qualified_table = self._qualified_table()
                    # Identifiers are validated/quoted; values are parameterized placeholders.
                    insert_sql = f"INSERT INTO {qualified_table} ({columns}) VALUES ({placeholders})"  # nosec B608

                    logger.info("Executing bulk insert with fast_executemany...")

                    # Execute bulk insert
                    cursor.executemany(insert_sql, rows)
                    raw_conn.commit()
                    fast_path_succeeded = True

                    logger.info("Bulk insert completed")

                finally:
                    raw_conn.close()
            except Exception:
                logger.warning(
                    "fast_executemany bulk insert failed, falling back to pandas.to_sql append",
                    exc_info=True,
                )

            if not fast_path_succeeded:
                self._fallback_insert(df_clean, chunk_size, **_kwargs)

            elapsed = time.time() - start_time
            logger.info(f"Successfully wrote {row_count} rows to {table_name} in {elapsed:.2f}s")
            logger.info(f"   Throughput: {row_count / elapsed:.0f} rows/sec")
        except Exception as exc:
            logger.error(f"Failed to write to MSSQL: {exc}", exc_info=True)
            raise CreateError(f"Failed to write to MSSQL: {exc!s}") from exc

    def _log_write_start(self, table_name: str, rows: int, cols: int, chunk_size: int | None) -> None:
        logger.info("Starting MSSQL write operation:")
        logger.info(f"   Table: {table_name}")
        logger.info(f"   Rows: {rows}")
        logger.info(f"   Columns: {cols}")
        logger.info(f"   Chunksize: {chunk_size}")
        logger.info(f"   Expected batches: {(rows + chunk_size - 1) // chunk_size if chunk_size else 1}")

    def _fallback_insert(self, df_clean: pd.DataFrame, chunk_size: int | None, **_kwargs: Any) -> None:
        """
        Append rows via pandas.to_sql as a safe fallback path.
        Returns:
            None
        """
        logger.info("Appending rows via pandas to_sql (method='multi') as fallback")
        df_clean.to_sql(
            name=self.settings.table_name,
            con=self.linked_service.engine,
            schema=self.settings.schema_name,
            if_exists="append",
            index=False,
            chunksize=chunk_size,
            method="multi",
            **_kwargs,
        )

    def update(self, **_kwargs: Any) -> None:
        """
        Update data in SQL Server table.
        For clone/copy workflow, this appends data (same as create).

        Args:
            _kwargs: Additional keyword arguments.

        Returns:
             None
        """
        # For clone/copy, update = create (just append data)
        self.create(**_kwargs)

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
        if self.settings.delete.delete_table:
            table_name = self._qualified_table()

            try:
                query = f"DROP TABLE IF EXISTS {table_name}"
                logger.debug(f"Dropping table: {table_name}")

                with self.linked_service.engine.connect() as conn:
                    conn.execute(text(query))
                    conn.commit()

                logger.info(f"Successfully dropped table: {table_name}")
            except Exception as exc:
                logger.error(f"Failed to delete table: {exc}", exc_info=True)
                raise DeleteError(f"Failed to delete table: {exc!s}") from exc
        else:
            if self.input is None or getattr(self.input, "empty", True):
                raise DeleteError("No input rows provided; refusing to delete all rows")

            df = self.input
            table_name = self._qualified_table()

            # Use all columns present in the input row as match criteria
            key_columns = list(df.columns)
            where_clause = " AND ".join([f"{self._quote_identifier(col)} = :{col}" for col in key_columns])
            delete_sql = text(f"DELETE FROM {table_name} WHERE {where_clause}")  # nosec B608

            payloads = [{col: row[col] for col in key_columns} for row in df.to_dict(orient="records")]

            try:
                with self.linked_service.engine.begin() as conn:
                    conn.execute(delete_sql, payloads)
                logger.info(f"Successfully deleted {len(payloads)} rows from table: {table_name}")
            except Exception as exc:
                logger.error(f"Failed to delete specific rows from table: {exc}", exc_info=True)
                raise DeleteError(f"Failed to delete specific rows from table: {exc!s}") from exc

    def rename(self, **_kwargs: Any) -> NoReturn:
        """
        Rename operation is not directly supported.
        Use SQL ALTER TABLE statements via update method.

        Raises:
            NotImplementedError: Always raised to indicate that rename is not supported.
        """
        raise NotImplementedError(
            "Rename operation is not directly supported. Use SQL ALTER TABLE statements via the update method with a custom query."
        )

    def close(self) -> None:
        pass
