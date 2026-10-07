CREATE TABLE `external_dataset` (
	`dataset_key` text PRIMARY KEY NOT NULL,
	`source_id` text NOT NULL,
	`portal` text NOT NULL,
	`dataset_id` text NOT NULL,
	`name` text,
	`title` text NOT NULL,
	`description` text,
	`description_truncated` integer DEFAULT 0 NOT NULL,
	`organization` text,
	`license` text,
	`license_url` text,
	`groups` text,
	`tags` text,
	`n_resources` integer DEFAULT 0 NOT NULL,
	`metadata_modified` text,
	`page_url` text NOT NULL,
	`api_url` text,
	`fetched_at` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_ed_source_modified` ON `external_dataset` (`source_id`,`metadata_modified`);--> statement-breakpoint
CREATE INDEX `ix_ed_org` ON `external_dataset` (`organization`);--> statement-breakpoint
CREATE TABLE `external_resource` (
	`resource_key` text PRIMARY KEY NOT NULL,
	`dataset_key` text NOT NULL,
	`name` text,
	`format` text,
	`size` integer,
	`last_modified` text,
	`direct_url` text,
	`page_url` text,
	`sheets_json` text
);
--> statement-breakpoint
CREATE INDEX `ix_er_dataset` ON `external_resource` (`dataset_key`);--> statement-breakpoint
CREATE INDEX `ix_er_format` ON `external_resource` (`format`);