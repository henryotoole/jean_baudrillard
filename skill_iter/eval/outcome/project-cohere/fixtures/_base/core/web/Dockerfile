FROM python:3.12-slim AS build
WORKDIR /service
COPY . .
RUN ./build.sh

FROM python:3.12-slim AS prod
WORKDIR /service
COPY --from=build /service/dist /service/dist
CMD ["python", "-m", "dist.main"]
