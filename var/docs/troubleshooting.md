# Troubleshooting

## asyncpg.exceptions.InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block

Preferred solution:
```python
# # always get a new database session for listeners
@injectable(use_cache=False)
```

Non preferred solution because you will need to mount the object:
```python
 async with SessionFactory() as session:
    repository = FooRepository(session)
```
