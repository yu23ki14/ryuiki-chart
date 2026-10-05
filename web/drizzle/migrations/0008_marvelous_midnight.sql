CREATE TABLE `summary_effort_year` (
	`year` integer,
	`n` integer NOT NULL,
	`n_binom` integer NOT NULL,
	`n_places` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `summary_grid_catalog` (
	`place_id` text,
	`n` integer NOT NULL,
	`n_red_list` integer NOT NULL,
	`n_binom` integer NOT NULL,
	`n_red_binom` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `summary_group_year` (
	`year` integer,
	`taxon_group` text,
	`source_id` text,
	`n` integer NOT NULL,
	`n_binom` integer NOT NULL,
	`n_places` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_group_year_year` ON `summary_group_year` (`year`);--> statement-breakpoint
CREATE TABLE `summary_species_catalog` (
	`binom` text,
	`taxon_group` text,
	`class` text,
	`family` text,
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
CREATE INDEX `ix_summary_species_catalog_binom` ON `summary_species_catalog` (`binom`);--> statement-breakpoint
ALTER TABLE `taxon_assessment` ADD `binom` text;