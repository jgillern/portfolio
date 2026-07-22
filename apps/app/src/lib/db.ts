import postgres, { type Sql } from "postgres";

let client: Sql | undefined;

export function databaseEnabled(): boolean {
  return process.env.DATA_MODE === "database" && Boolean(process.env.DATABASE_READ_URL);
}

export function readDatabase(): Sql {
  const url = process.env.DATABASE_READ_URL;
  if (!databaseEnabled() || !url) {
    throw new Error("The read-only database connection is not configured.");
  }
  client ??= postgres(url, {
    max: 2,
    idle_timeout: 20,
    connect_timeout: 10,
    prepare: false,
  });
  return client;
}
