FROM docker.io/library/node:24-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY server.js loadgen.js ./
CMD ["node", "server.js"]
