CREATE TABLE `hazard_zones` (
	`zone_id` text PRIMARY KEY NOT NULL,
	`site_code` text,
	`site_name_ja` text,
	`phenomenon_code` text,
	`phenomenon_ja` text,
	`zone_kind_code` text,
	`zone_kind_ja` text,
	`municipality_ja` text,
	`locality_ja` text,
	`river_name_ja` text,
	`office_ja` text,
	`designated_on` text,
	`designated_on_raw` text,
	`notice_no_raw` text,
	`area_m2` real,
	`centroid_lat` real,
	`centroid_lon` real,
	`watershed` text,
	`geometry_geojson` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_hz` ON `hazard_zones` (`source_id`,`phenomenon_code`,`zone_kind_code`,`municipality_ja`);--> statement-breakpoint
CREATE INDEX `ix_hz_source` ON `hazard_zones` (`source_id`,`zone_id`);