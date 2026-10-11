CREATE TABLE `summary_taxon_red_list` (
	`region_id` text NOT NULL,
	`taxon_id` text NOT NULL,
	`red_list_category` text NOT NULL,
	`red_list_source` text,
	`n` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_taxon_red_list_taxon` ON `summary_taxon_red_list` (`taxon_id`);--> statement-breakpoint
CREATE INDEX `ix_summary_taxon_red_list_region_taxon` ON `summary_taxon_red_list` (`region_id`,`taxon_id`);