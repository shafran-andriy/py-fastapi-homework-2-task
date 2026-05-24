from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from database import get_db, MovieModel
from database.models import (CountryModel,
                             GenreModel,
                             ActorModel,
                             LanguageModel
                             )
from schemas.movies import (MovieListResponseSchema,
                            MovieDetailResponseSchema,
                            MovieCreateSchema,
                            MovieUpdateSchema
                            )

router = APIRouter()


def validate_date_not_too_far_in_future(cls, value: datetime.date) -> datetime.date:
    max_allowed_date = datetime.date.today() + datetime.timedelta(days=365)
    if value > max_allowed_date:
        raise ValueError("Date must not be more than one year in the future.")
    return value

@router.get("/movies/", response_model=MovieListResponseSchema)
async def get_movies(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> MovieListResponseSchema:
    total_items = await db.scalar(select(func.count()).select_from(MovieModel))
    total_items = total_items or 0

    offset = (page - 1) * per_page
    result = await db.execute(
        select(MovieModel)
        .order_by(MovieModel.id)
        .offset(offset)
        .limit(per_page)
    )
    movies = list(result.scalars().all())

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")

    total_pages = (total_items + per_page - 1) // per_page
    base_url = "/api/v1/theater/movies/"

    prev_page = None
    if page > 1:
        prev_page = f"{base_url}?page={page - 1}&per_page={per_page}"

    next_page = None
    if page < total_pages:
        next_page = f"{base_url}?page={page + 1}&per_page={per_page}"

    return MovieListResponseSchema(
        movies=movies,
        prev_page=prev_page,
        next_page=next_page,
        total_pages=total_pages,
        total_items=total_items,
    )


@router.get("/movies/{movie_id}/", response_model=MovieDetailResponseSchema)
async def get_movie_by_id(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
) -> MovieDetailResponseSchema:
    movie = await db.get(MovieModel, movie_id)

    if movie is None:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found.",
        )

    return MovieDetailResponseSchema.model_validate(movie)