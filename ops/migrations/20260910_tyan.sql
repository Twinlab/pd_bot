-- История /tyan; существующие таблицы не изменяются.
CREATE TABLE IF NOT EXISTS "tyan_rolls" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "discord_user_id" BIGINT NOT NULL,
    "date" DATE NOT NULL,
    "kind" VARCHAR(16) NOT NULL,
    "adjective_id" VARCHAR(80),
    "archetype_id" VARCHAR(80),
    "trait_id" VARCHAR(80),
    "age" INT,
    "height" INT,
    "weight" INT,
    "target_user_id" BIGINT,
    "text" TEXT NOT NULL,
    "created_at" TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "uid_tyan_user_date" UNIQUE ("discord_user_id", "date")
);
CREATE INDEX IF NOT EXISTS "idx_tyan_date" ON "tyan_rolls" ("date");
CREATE INDEX IF NOT EXISTS "idx_tyan_kind_created" ON "tyan_rolls" ("kind", "created_at");
