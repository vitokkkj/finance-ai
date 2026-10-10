FROM node:24-alpine AS base

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /workspace/apps/web

FROM base AS dependencies
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM dependencies AS development
COPY apps/web ./
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

FROM base AS builder
COPY --from=dependencies /workspace/apps/web/node_modules ./node_modules
COPY apps/web ./
RUN npm run build && npm prune --omit=dev

FROM node:24-alpine AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /workspace/apps/web
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs nextjs
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/public ./public
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/.next-production ./.next-production
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/package.json ./package.json
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/next.config.ts ./next.config.ts
USER nextjs
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
