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
# Run as the image's built-in non-root user (security review F9). `next start`
# only writes its runtime cache under .next, so own just that tree, and do it
# at copy time (one pass). A separate `RUN chown -R /app` would re-walk the
# whole node_modules tree, which is pathologically slow on some filesystems.
# node_modules and public stay root-owned and world-readable, which is all
# `next start` needs to read them.
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
USER node
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-H", "0.0.0.0"]
