CREATE TABLE `place_region` (
	`place_id` text NOT NULL,
	`region_id` text NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_place_region_place` ON `place_region` (`place_id`);--> statement-breakpoint
CREATE INDEX `ix_place_region_region_place` ON `place_region` (`region_id`,`place_id`);--> statement-breakpoint
CREATE TABLE `summary_effort_year_by_region` (
	`region_id` text NOT NULL,
	`year` integer,
	`n` integer NOT NULL,
	`n_binom` integer NOT NULL,
	`n_places` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_effort_year_by_region_region_year` ON `summary_effort_year_by_region` (`region_id`,`year`);--> statement-breakpoint
CREATE TABLE `summary_species_catalog_by_region` (
	`region_id` text NOT NULL,
	`binom` text,
	`taxon_group` text,
	`class` text,
	`family` text,
	`n` integer NOT NULL,
	`n_located` integer DEFAULT 0 NOT NULL,
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
CREATE INDEX `ix_summary_species_catalog_by_region_region_binom` ON `summary_species_catalog_by_region` (`region_id`,`binom`);--> statement-breakpoint
CREATE TABLE `summary_taxon_catalog_by_region` (
	`region_id` text NOT NULL,
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
CREATE INDEX `ix_summary_taxon_catalog_by_region_region_taxon` ON `summary_taxon_catalog_by_region` (`region_id`,`taxon_id`);--> statement-breakpoint
CREATE TABLE `summary_variable_catalog_by_region` (
	`region_id` text NOT NULL,
	`variable_id` text,
	`obs_stat` text,
	`unit_id` text,
	`value_grain` text,
	`grain` text,
	`input_grain` text,
	`n` integer NOT NULL,
	`n_places` integer NOT NULL,
	`y_from` integer,
	`y_to` integer,
	`n_censored` integer NOT NULL,
	`n_not_detected` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_variable_catalog_by_region_region_variable` ON `summary_variable_catalog_by_region` (`region_id`,`variable_id`);