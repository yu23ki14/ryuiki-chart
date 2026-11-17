CREATE TABLE `osm_water_structures` (
	`osm_type` text NOT NULL,
	`osm_id` integer NOT NULL,
	`kind` text NOT NULL,
	`name_ja` text,
	`region_id` text,
	`lat` real,
	`lon` real,
	`source_id` text NOT NULL,
	`source_ref` text,
	PRIMARY KEY(`osm_type`, `osm_id`)
);
--> statement-breakpoint
CREATE INDEX `ix_osmws_region` ON `osm_water_structures` (`region_id`,`kind`);--> statement-breakpoint
CREATE UNIQUE INDEX `ux_osmws_ref` ON `osm_water_structures` (`source_ref`);--> statement-breakpoint
CREATE TABLE `osm_waterways` (
	`way_id` integer PRIMARY KEY NOT NULL,
	`name_ja` text,
	`waterway` text NOT NULL,
	`relation_id` integer,
	`region_id` text,
	`length_m` real,
	`geometry_geojson` text,
	`start_lat` real,
	`start_lon` real,
	`end_lat` real,
	`end_lon` real,
	`source_id` text NOT NULL,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `ix_osmw_region` ON `osm_waterways` (`region_id`,`waterway`);--> statement-breakpoint
CREATE INDEX `ix_osmw_rel` ON `osm_waterways` (`relation_id`);