import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
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


def validate_date_not_too_far_in_future(value: datetime.date) -> None:
    max_allowed_date = datetime.date.today() + datetime.timedelta(days=365)
    if value > max_allowed_date:
        raise HTTPException(status_code=400, detail="Invalid input data.")


async def get_or_create_by_name(
    db: AsyncSession,
    model: type[GenreModel] | type[ActorModel] | type[LanguageModel],
    name: str,
) -> GenreModel | ActorModel | LanguageModel:
    result = await db.execute(select(model).where(model.name == name))
    instance = result.scalars().first()

    if instance is None:
        instance = model(name=name)
        db.add(instance)
        await db.flush()

    return instance


async def get_movie_with_relations(
    db: AsyncSession,
    movie_id: int,
) -> MovieModel | None:
    result = await db.execute(
        select(MovieModel)
        .options(
            joinedload(MovieModel.country),
            joinedload(MovieModel.genres),
            joinedload(MovieModel.actors),
            joinedload(MovieModel.languages),
        )
        .where(MovieModel.id == movie_id)
    )
    return result.unique().scalars().first()


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
        .order_by(MovieModel.id.desc())
        .offset(offset)
        .limit(per_page)
    )
    movies = list(result.scalars().all())

    if not movies:
        raise HTTPException(status_code=404, detail="No movies found.")

    total_pages = (total_items + per_page - 1) // per_page
    base_url = "/theater/movies/"

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
    movie = await get_movie_with_relations(db, movie_id)

    if movie is None:
        raise HTTPException(
            status_code=404,
            detail="Movie with the given ID was not found.",
        )

    return MovieDetailResponseSchema.model_validate(movie)


@router.post(
    "/movies/",
    response_model=MovieDetailResponseSchema,
    status_code=status.HTTP_201_CREATED,
)
async def create_movie(
    movie_data: MovieCreateSchema,
    db: AsyncSession = Depends(get_db),
) -> MovieDetailResponseSchema:
    validate_date_not_too_far_in_future(movie_data.date)

    duplicate_result = await db.execute(
        select(MovieModel).where(
            MovieModel.name == movie_data.name,
            MovieModel.date == movie_data.date,
        )
    )
    duplicate_movie = duplicate_result.scalars().first()
    if duplicate_movie is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A movie with the name '{movie_data.name}' and release date "
                f"'{movie_data.date}' already exists."
            ),
        )

    country_result = await db.execute(
        select(CountryModel).where(CountryModel.code == movie_data.country)
    )
    country = country_result.scalars().first()
    if country is None:
        country = CountryModel(code=movie_data.country, name=None)
        db.add(country)
        await db.flush()

    genres = [
        await get_or_create_by_name(db, GenreModel, genre_name)
        for genre_name in movie_data.genres
    ]
    actors = [
        await get_or_create_by_name(db, ActorModel, actor_name)
        for actor_name in movie_data.actors
    ]
    languages = [
        await get_or_create_by_name(db, LanguageModel, language_name)
        for language_name in movie_data.languages
    ]

    movie = MovieModel(
        name=movie_data.name,
        date=movie_data.date,
        score=movie_data.score,
        overview=movie_data.overview,
        status=movie_data.status,
        budget=movie_data.budget,
        revenue=movie_data.revenue,
        country=country,
        genres=genres,
        actors=actors,
        languages=languages,
    )
    db.add(movie)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")

    created_movie = await get_movie_with_relations(db, movie.id)
    return MovieDetailResponseSchema.model_validate(created_movie)


@router.delete("/movies/{movie_id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_movie(
    movie_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    movie = await db.get(MovieModel, movie_id)

    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given ID was not found.",
        )

    await db.delete(movie)
    await db.commit()


@router.patch("/movies/{movie_id}/")
async def update_movie(
    movie_id: int,
    movie_data: MovieUpdateSchema,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    movie = await db.get(MovieModel, movie_id)

    if movie is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given ID was not found.",
        )

    update_data = movie_data.model_dump(exclude_unset=True)
    if "date" in update_data:
        validate_date_not_too_far_in_future(update_data["date"])

    for field, value in update_data.items():
        setattr(movie, field, value)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid input data.")

    return {"detail": "Movie updated successfully."}
