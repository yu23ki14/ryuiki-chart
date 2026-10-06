ALTER TABLE `unit` ADD `canonical_unit_id` text;--> statement-breakpoint
ALTER TABLE `unit` ADD `scale_to_canonical` real DEFAULT 1 NOT NULL;--> statement-breakpoint
ALTER TABLE `variable_alias` ADD `unit_basis` text;