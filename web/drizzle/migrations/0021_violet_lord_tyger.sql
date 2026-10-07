CREATE TABLE `external_resource_format` (
	`dataset_key` text NOT NULL,
	`format_norm` text NOT NULL,
	`resource_key` text NOT NULL,
	PRIMARY KEY(`dataset_key`, `format_norm`, `resource_key`)
);
--> statement-breakpoint
CREATE INDEX `ix_erf_format` ON `external_resource_format` (`format_norm`,`dataset_key`);--> statement-breakpoint
DROP INDEX `ix_er_format`;--> statement-breakpoint
ALTER TABLE `external_dataset` ADD `n_with_header` integer DEFAULT 0 NOT NULL;