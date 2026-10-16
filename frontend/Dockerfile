FROM node:20-alpine AS builder
WORKDIR /app
# npm ci installs exactly what package-lock.json pins (the versions used and
# tested locally) and fails if the lockfile and package.json disagree. The
# old pnpm install --no-frozen-lockfile ignored its lockfile, so every build
# pulled whatever was newest that day, untested.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# NEXT_PUBLIC_* must exist at build time to be baked into the client bundle.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-H", "0.0.0.0"]
