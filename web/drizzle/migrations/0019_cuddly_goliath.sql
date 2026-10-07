ALTER TABLE `source_access` ADD `record_set_rows` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
CREATE INDEX `ix_mammal_source` ON `mammal_mesh` (`source_id`,`id`);--> statement-breakpoint
CREATE INDEX `ix_veg_source` ON `vegetation_polygons` (`source_id`,`feature_id`);--> statement-breakpoint
CREATE INDEX `ix_taxon_assessment_source` ON `taxon_assessment` (`source_id`,`assessment_id`);