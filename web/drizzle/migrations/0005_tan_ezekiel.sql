ALTER TABLE `taxon` ADD `canonical_binomial` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `kingdom` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `phylum` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `class` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `order` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `family` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `classification_basis` text;--> statement-breakpoint
ALTER TABLE `taxon` ADD `taxon_group` text;--> statement-breakpoint
CREATE INDEX `ix_taxon_binomial` ON `taxon` (`canonical_binomial`);