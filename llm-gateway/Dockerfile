FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /llm-gateway .

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /llm-gateway /llm-gateway
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/llm-gateway"]
