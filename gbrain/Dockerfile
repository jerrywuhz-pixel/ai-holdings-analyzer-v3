FROM oven/bun:1 AS base
WORKDIR /app

# Install dependencies
COPY package.json ./
RUN bun install

# Copy source
COPY src/ src/
COPY tsconfig.json ./

# Run
CMD ["bun", "run", "src/mcp-adapter.ts"]
