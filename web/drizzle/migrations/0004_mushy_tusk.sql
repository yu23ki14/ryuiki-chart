ALTER TABLE `variable_alias` RENAME COLUMN "source_scope" TO "dataset";--> statement-breakpoint
ALTER TABLE `variable_alias` ADD `source_id` text;--> statement-breakpoint
CREATE INDEX `ix_variable_alias_dataset_alias_source` ON `variable_alias` (`dataset`,`alias`,`source_id`);