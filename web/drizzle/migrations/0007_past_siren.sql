CREATE TABLE `summary_taxon_catalog` (
	`taxon_id` text,
	`n` integer NOT NULL,
	`n_red_list` integer NOT NULL,
	`n_alien` integer NOT NULL,
	`n_places` integer NOT NULL,
	`y_from` integer,
	`y_to` integer,
	`n_years` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_taxon_catalog_taxon` ON `summary_taxon_catalog` (`taxon_id`);--> statement-breakpoint
CREATE TABLE `summary_watershed_occurrence` (
	`place_id` text,
	`n` integer NOT NULL,
	`n_red_list` integer NOT NULL,
	`n_alien` integer NOT NULL,
	`n_taxa` integer NOT NULL,
	`y_from` integer,
	`y_to` integer,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_watershed_occurrence_place` ON `summary_watershed_occurrence` (`place_id`);--> statement-breakpoint
ALTER TABLE `taxon` ADD `vernacular_name_en` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `vernacular_ja_basis` text;--> statement-breakpoint
ALTER TABLE `taxon_assessment` ADD `in_scope` integer;--> statement-breakpoint
ALTER TABLE `occurrence_agg` ADD `n_alien` integer NOT NULL;--> statement-breakpoint
CREATE INDEX `ix_occurrence_agg_kind_grain_period` ON `occurrence_agg` (`place_kind`,`grain`,`period_start`);