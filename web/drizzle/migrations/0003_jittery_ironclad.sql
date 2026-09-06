CREATE TABLE `caveat` (
	`caveat_id` text PRIMARY KEY NOT NULL,
	`severity` text,
	`kind` text,
	`title_ja` text,
	`body_ja` text,
	`quote` text
);
--> statement-breakpoint
CREATE TABLE `caveat_scope` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`caveat_id` text,
	`scope_kind` text,
	`scope_ref` text,
	`sort_order` integer
);
--> statement-breakpoint
CREATE INDEX `ix_caveat_scope_scope` ON `caveat_scope` (`scope_kind`,`scope_ref`);--> statement-breakpoint
CREATE INDEX `ix_caveat_scope_caveat` ON `caveat_scope` (`caveat_id`);--> statement-breakpoint
CREATE TABLE `place` (
	`place_id` text PRIMARY KEY NOT NULL,
	`region_id` text,
	`place_kind` text,
	`name_ja` text,
	`lat` real,
	`lon` real,
	`elevation_m` real,
	`area_km2` real,
	`definition_ref` text,
	`status` text
);
--> statement-breakpoint
CREATE INDEX `ix_place_kind` ON `place` (`place_kind`);--> statement-breakpoint
CREATE TABLE `place_source_ref` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`place_id` text,
	`external_key` text,
	`source_id` text
);
--> statement-breakpoint
CREATE INDEX `ix_place_source_ref_external` ON `place_source_ref` (`external_key`);--> statement-breakpoint
CREATE INDEX `ix_place_source_ref_place` ON `place_source_ref` (`place_id`);--> statement-breakpoint
CREATE TABLE `taxon` (
	`taxon_id` text PRIMARY KEY NOT NULL,
	`scientific_name` text,
	`rank` text,
	`gbif_taxon_key` text,
	`vernacular_name_ja` text,
	`status` text,
	`accepted_taxon_id` text
);
--> statement-breakpoint
CREATE INDEX `ix_taxon_gbif_key` ON `taxon` (`gbif_taxon_key`);--> statement-breakpoint
CREATE TABLE `unit` (
	`unit_id` text PRIMARY KEY NOT NULL,
	`symbol` text,
	`ucum` text,
	`name_ja` text,
	`quantity_kind` text
);
--> statement-breakpoint
CREATE TABLE `variable` (
	`variable_id` text PRIMARY KEY NOT NULL,
	`code` text,
	`name_ja` text,
	`name_en` text,
	`theme` text,
	`unit_id` text,
	`value_type` text,
	`default_stat` text,
	`higher_is_worse` integer,
	`description_ja` text,
	`status` text
);
--> statement-breakpoint
CREATE TABLE `variable_alias` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`alias` text NOT NULL,
	`source_scope` text,
	`variable_id` text,
	`unit_id` text,
	`stat` text,
	`grain` text,
	`note` text
);
--> statement-breakpoint
CREATE INDEX `ix_variable_alias_alias` ON `variable_alias` (`alias`);--> statement-breakpoint
CREATE INDEX `ix_variable_alias_variable` ON `variable_alias` (`variable_id`);