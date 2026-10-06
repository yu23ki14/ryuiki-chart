ALTER TABLE `place_source_ref` RENAME COLUMN "source_id" TO "key_space";--> statement-breakpoint
ALTER TABLE `place_source_ref` ADD `source_edition_id` text;