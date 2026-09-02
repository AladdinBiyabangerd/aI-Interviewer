import "server-only";

import postgres, { type Sql } from "postgres";

import { databaseUrl } from "./config";

declare global {
  var __interviewDatabase: Sql | undefined;
}

export function database(): Sql {
  if (!globalThis.__interviewDatabase) {
    globalThis.__interviewDatabase = postgres(databaseUrl(), {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
      transform: { undefined: null },
    });
  }
  return globalThis.__interviewDatabase;
}
