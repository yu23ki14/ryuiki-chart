CREATE TABLE `edna_reads` (
	`read_id` text PRIMARY KEY NOT NULL,
	`site_key` text NOT NULL,
	`class_ja` text,
	`order_ja` text,
	`family_ja` text,
	`genus_ja` text,
	`name_raw` text,
	`name_adopted` text,
	`name_sci_raw` text,
	`name_note` text,
	`reads` integer NOT NULL,
	`is_detected` integer NOT NULL,
	`pident_qcov` real,
	`reliability` text,
	`national_rl_raw` text,
	`pref_rl_raw` text,
	`alien_raw` text,
	`name_key` text NOT NULL,
	`taxon_id` text,
	`source_id` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_edna_reads_site` ON `edna_reads` (`site_key`,`is_detected`);--> statement-breakpoint
CREATE INDEX `ix_edna_reads_taxon` ON `edna_reads` (`taxon_id`,`is_detected`);--> statement-breakpoint
CREATE TABLE `edna_sites` (
	`site_key` text PRIMARY KEY NOT NULL,
	`dataset_file` text NOT NULL,
	`program` text NOT NULL,
	`assay` text NOT NULL,
	`fiscal_year` integer NOT NULL,
	`site_id_raw` text NOT NULL,
	`water_system_raw` text,
	`water_system_ja` text,
	`tributary_raw` text,
	`tributary_ja` text,
	`municipality_raw` text,
	`municipality_ja` text,
	`collected_on` text,
	`collected_on_raw` text,
	`lat` real,
	`lon` real,
	`coord_source` text NOT NULL,
	`coordinate_uncertainty_m` real,
	`coord_method` text,
	`coord_note` text,
	`source_id` text NOT NULL,
	`source_ref` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_edna_sites_date` ON `edna_sites` (`collected_on`);--> statement-breakpoint
CREATE INDEX `ix_edna_sites_region` ON `edna_sites` (`water_system_ja`,`tributary_ja`);