FROM node:22.17.0-alpine@sha256:fc3e945f920b7e3000cd1af86c4ae406ec70c72f328b667baf0f3a8910d69eed AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS builder
ARG NEXT_PUBLIC_API_BASE_URL=/api
ARG NEXT_PUBLIC_RAZORPAY_KEY_ID
ARG NEXT_PUBLIC_SUPPORT_EMAIL
ARG NEXT_PUBLIC_PRIVACY_EMAIL
ARG NEXT_PUBLIC_LEGAL_EMAIL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_RAZORPAY_KEY_ID=$NEXT_PUBLIC_RAZORPAY_KEY_ID
ENV NEXT_PUBLIC_SUPPORT_EMAIL=$NEXT_PUBLIC_SUPPORT_EMAIL
ENV NEXT_PUBLIC_PRIVACY_EMAIL=$NEXT_PUBLIC_PRIVACY_EMAIL
ENV NEXT_PUBLIC_LEGAL_EMAIL=$NEXT_PUBLIC_LEGAL_EMAIL
COPY . .
RUN test -n "$NEXT_PUBLIC_RAZORPAY_KEY_ID" \
    && test -n "$NEXT_PUBLIC_SUPPORT_EMAIL" \
    && test -n "$NEXT_PUBLIC_PRIVACY_EMAIL" \
    && test -n "$NEXT_PUBLIC_LEGAL_EMAIL" \
    && npm run build

FROM node:22.17.0-alpine@sha256:fc3e945f920b7e3000cd1af86c4ae406ec70c72f328b667baf0f3a8910d69eed AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN addgroup -S interai && adduser -S interai -G interai
COPY --from=builder --chown=interai:interai /app/public ./public
COPY --from=builder --chown=interai:interai /app/.next/standalone ./
COPY --from=builder --chown=interai:interai /app/.next/static ./.next/static
USER interai
EXPOSE 3000
CMD ["node", "server.js"]
