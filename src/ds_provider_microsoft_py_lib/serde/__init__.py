"""
**File:** ``__init__.py``
**Region:** ``ds-provider-microsoft-py-lib/serde``

Serialization and deserialization for Microsoft provider.

Example:
>>> data_frame = pd.DataFrame(...)
>>> serializer = MsSqlTableSerializer()
>>> cleaned_df, rows = serializer(data_frame)
"""
