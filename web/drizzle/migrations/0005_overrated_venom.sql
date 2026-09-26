CREATE TABLE `place_relation` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`parent_id` text NOT NULL,
	`child_id` text NOT NULL,
	`relation` text NOT NULL,
	`fraction` real NOT NULL,
	`basis` text
);
--> statement-breakpoint
CREATE INDEX `ix_place_relation_parent` ON `place_relation` (`parent_id`);--> statement-breakpoint
CREATE INDEX `ix_place_relation_child` ON `place_relation` (`child_id`);--> statement-breakpoint
CREATE TABLE `place_watershed` (
	`place_id` text PRIMARY KEY NOT NULL,
	`water_system_code` text,
	`water_system_category` text,
	`main_rivers` text,
	`data_year` integer
);
--> statement-breakpoint
CREATE TABLE `taxon_assessment` (
	`assessment_id` text PRIMARY KEY NOT NULL,
	`list_id` text NOT NULL,
	`list_year` integer,
	`taxon_id` text,
	`scientific_name_raw` text,
	`vernacular_name_ja_raw` text,
	`vernacular_name_ja_resolved` text,
	`taxon_group_ja` text,
	`taxon_subgroup_ja` text,
	`family_ja` text,
	`category_raw` text,
	`category_code` text,
	`prev_category_raw` text,
	`prev_category_code` text,
	`national_category_raw` text,
	`origin` text,
	`source_id` text
);
--> statement-breakpoint
CREATE INDEX `ix_taxon_assessment_list` ON `taxon_assessment` (`list_id`);--> statement-breakpoint
CREATE INDEX `ix_taxon_assessment_taxon` ON `taxon_assessment` (`taxon_id`);--> statement-breakpoint
CREATE TABLE `observation_agg` (
	`region_id` text,
	`place_id` text,
	`place_kind` text,
	`variable_id` text,
	`obs_stat` text,
	`unit_id` text,
	`value_grain` text,
	`period_start` text,
	`period_end` text,
	`grain` text,
	`input_grain` text,
	`stat` text,
	`value_zero` real,
	`value_lod` real,
	`n` integer NOT NULL,
	`n_censored` integer NOT NULL,
	`n_not_detected` integer NOT NULL,
	`n_places` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_observation_agg_variable_place_grain_stat_period` ON `observation_agg` (`variable_id`,`place_id`,`grain`,`stat`,`period_start`);--> statement-breakpoint
CREATE INDEX `ix_observation_agg_place_variable_grain` ON `observation_agg` (`place_id`,`variable_id`,`grain`);--> statement-breakpoint
CREATE TABLE `occurrence_agg` (
	`region_id` text NOT NULL,
	`source_id` text NOT NULL,
	`place_id` text,
	`place_kind` text,
	`taxon_id` text,
	`grain` text NOT NULL,
	`period_start` text NOT NULL,
	`period_end` text NOT NULL,
	`n` integer NOT NULL,
	`n_red_list` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_occurrence_agg_taxon_period` ON `occurrence_agg` (`taxon_id`,`period_start`);--> statement-breakpoint
CREATE INDEX `ix_occurrence_agg_place_period` ON `occurrence_agg` (`place_id`,`period_start`);--> statement-breakpoint
ALTER TABLE `taxon` ADD `canonical_binomial` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `class` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `family` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `taxon_group` text;--> statement-breakpoint
CREATE INDEX `ix_taxon_binomial` ON `taxon` (`canonical_binomial`);