CREATE TABLE `water_facility` (
	`facility_id` text PRIMARY KEY NOT NULL,
	`utility_id` text,
	`name` text,
	`type` text,
	`lat` real,
	`lon` real,
	`note_ja` text,
	`source_doc_id` text
);
--> statement-breakpoint
CREATE INDEX `ix_wfac_utility` ON `water_facility` (`utility_id`);--> statement-breakpoint
CREATE TABLE `water_flow_edge` (
	`edge_id` text PRIMARY KEY NOT NULL,
	`from_id` text,
	`to_id` text,
	`share` real,
	`basis` text,
	`valid_from` text,
	`valid_to` text,
	`source_doc_id` text,
	`note_ja` text
);
--> statement-breakpoint
CREATE INDEX `ix_wedge_to` ON `water_flow_edge` (`to_id`,`valid_from`);--> statement-breakpoint
CREATE TABLE `water_source` (
	`source_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`type` text,
	`river_system` text,
	`parent_id` text,
	`river_name_ja` text,
	`lat` real,
	`lon` real,
	`note_ja` text,
	`source_doc_id` text
);
--> statement-breakpoint
CREATE TABLE `water_source_doc` (
	`doc_id` text PRIMARY KEY NOT NULL,
	`title` text,
	`publisher` text,
	`url` text,
	`published_at` text,
	`retrieved_at` text,
	`local_path` text,
	`sha256` text,
	`license_ja` text
);
--> statement-breakpoint
CREATE TABLE `water_utility` (
	`utility_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`kind` text,
	`note_ja` text
);
--> statement-breakpoint
CREATE TABLE `water_zone` (
	`key_code` text PRIMARY KEY NOT NULL,
	`muni_code` text,
	`city_name` text,
	`s_name` text,
	`name` text,
	`parts` integer,
	`population` integer,
	`households` integer,
	`area_km2` real,
	`centroid_lat` real,
	`centroid_lon` real
);
--> statement-breakpoint
CREATE INDEX `ix_wzone_city` ON `water_zone` (`city_name`);--> statement-breakpoint
CREATE TABLE `water_zone_assignment` (
	`assignment_id` text PRIMARY KEY NOT NULL,
	`key_code` text,
	`facility_id` text,
	`share` real,
	`confidence` text,
	`valid_from` text,
	`valid_to` text,
	`source_doc_id` text,
	`note_ja` text
);
--> statement-breakpoint
CREATE INDEX `ix_wza_key` ON `water_zone_assignment` (`key_code`);--> statement-breakpoint
CREATE INDEX `ix_wza_fac` ON `water_zone_assignment` (`facility_id`);--> statement-breakpoint
CREATE TABLE `water_zone_source_share` (
	`key_code` text,
	`source_id` text,
	`share` real,
	`confidence` text,
	`basis` text,
	`as_of` text
);
--> statement-breakpoint
CREATE INDEX `ix_wzss_key` ON `water_zone_source_share` (`key_code`);--> statement-breakpoint
CREATE INDEX `ix_wzss_src` ON `water_zone_source_share` (`source_id`);