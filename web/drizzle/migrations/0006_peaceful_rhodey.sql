CREATE TABLE `summary_place_variable` (
	`place_id` text,
	`variable_id` text,
	`obs_stat` text,
	`unit_id` text,
	`value_grain` text,
	`grain` text,
	`input_grain` text,
	`n` integer NOT NULL,
	`y_from` integer,
	`y_to` integer,
	`avg_zero` real,
	`avg_lod` real,
	`n_censored` integer NOT NULL,
	`n_not_detected` integer NOT NULL,
	`built_from` text NOT NULL,
	`spec_version` text NOT NULL
);
--> statement-breakpoint
CREATE INDEX `ix_summary_place_variable_place` ON `summary_place_variable` (`place_id`);--> statement-breakpoint
CREATE INDEX `ix_summary_place_variable_variable` ON `summary_place_variable` (`variable_id`);--> statement-breakpoint
CREATE TABLE `summary_variable_catalog` (
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
CREATE INDEX `ix_summary_variable_catalog_variable` ON `summary_variable_catalog` (`variable_id`);