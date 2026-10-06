CREATE TABLE `license` (
	`license_id` text PRIMARY KEY NOT NULL,
	`name_ja` text,
	`spdx_or_url` text,
	`license_class` text NOT NULL,
	`attribution_text` text,
	`notes` text
);
--> statement-breakpoint
CREATE TABLE `source` (
	`source_id` text PRIMARY KEY NOT NULL,
	`source_ref_id` text NOT NULL,
	`name_ja` text,
	`publisher` text,
	`homepage_url` text,
	`region_id` text,
	`theme` text,
	`access_method` text,
	`superseded_by` text,
	`notes` text
);
--> statement-breakpoint
CREATE TABLE `source_edition` (
	`edition_id` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`edition_key` text NOT NULL,
	`vintage` text,
	`fetched_at` text,
	`url` text,
	`format` text,
	`content_sha256` text,
	`license_id` text NOT NULL,
	`license_raw` text,
	`license_class` text NOT NULL,
	`redistributable` integer,
	`commercial_ok` integer,
	`record_count` integer,
	`superseded_by` text,
	`update_mode` text,
	`notes` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `ux_source_edition_source_key` ON `source_edition` (`source_id`,`edition_key`);--> statement-breakpoint
ALTER TABLE `variable_alias` ADD `edition_key` text;--> statement-breakpoint
ALTER TABLE `variable_alias` ADD `source_edition_id` text;