from pydantic import BaseModel


class PaginatedOutput[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
