CREATE TABLE `source_access` (
	`source_id` text PRIMARY KEY NOT NULL,
	`state` text NOT NULL,
	`queryable_via` text NOT NULL,
	`tables` text NOT NULL,
	`n_source_rows` integer,
	`n_source_rows_basis` text NOT NULL,
	`counted_at` text,
	`reason` text,
	`reason_ja` text,
	`reason_note` text
);
