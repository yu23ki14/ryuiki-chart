CREATE TABLE `mammal_mesh` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`mesh_code` text,
	`species` text,
	`species_ja` text,
	`survey_label` text,
	`survey_year` integer,
	`confirmed` integer,
	`lat` real,
	`lon` real,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_mammal` ON `mammal_mesh` (`species`,`survey_year`,`mesh_code`);--> statement-breakpoint
CREATE TABLE `protected_areas` (
	`area_id` text PRIMARY KEY NOT NULL,
	`name_ja` text,
	`category_ja` text,
	`category_code` text,
	`municipality_ja` text,
	`area_ha` real,
	`area_ha_raw` text,
	`designated_on` text,
	`designated_on_raw` text,
	`lat` real,
	`lon` real,
	`watershed` text,
	`zone` integer,
	`note_ja` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_pa_cat` ON `protected_areas` (`category_code`,`municipality_ja`);--> statement-breakpoint
CREATE TABLE `river_segments` (
	`feature_id` text PRIMARY KEY NOT NULL,
	`name_ja` text,
	`section_type` text,
	`prefecture_ja` text,
	`length_m` real,
	`start_lat` real,
	`start_lon` real,
	`end_lat` real,
	`end_lon` real,
	`geometry_geojson` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_river_pref` ON `river_segments` (`prefecture_ja`);--> statement-breakpoint
CREATE TABLE `vegetation_polygons` (
	`feature_id` text PRIMARY KEY NOT NULL,
	`legend_code` text,
	`legend_name_ja` text,
	`veg_division_ja` text,
	`naturalness` real,
	`naturalness_class_ja` text,
	`survey_year` integer,
	`block_ja` text,
	`area_m2` real,
	`centroid_lat` real,
	`centroid_lon` real,
	`watershed` text,
	`geometry_geojson` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_veg_legend` ON `vegetation_polygons` (`legend_code`);--> statement-breakpoint
CREATE TABLE `wildlife_sightings` (
	`sighting_id` text PRIMARY KEY NOT NULL,
	`species_ja` text,
	`fiscal_year` integer,
	`observed_on` text,
	`observed_on_raw` text,
	`observed_time_raw` text,
	`individual_count` real,
	`individual_count_raw` text,
	`situation_ja` text,
	`locality_ja` text,
	`area_kind_ja` text,
	`municipality_ja` text,
	`lat` real,
	`lon` real,
	`is_preliminary` integer DEFAULT 0,
	`note_ja` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_ws` ON `wildlife_sightings` (`species_ja`,`fiscal_year`);