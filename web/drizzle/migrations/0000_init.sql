CREATE TABLE `cells` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`doc_id` text NOT NULL,
	`doc_sha256` text,
	`page_no` integer,
	`table_id` text,
	`row_key` text,
	`col_key` text,
	`value_raw` text,
	`value` text,
	`value_type` text,
	`unit` text,
	`fiscal_year` integer,
	`era_raw` text,
	`source_text` text,
	`source_bbox` text,
	`notes_ref` text,
	`is_total` integer DEFAULT 0,
	`merged` integer DEFAULT 0,
	`unreadable_reason` text,
	`confidence` real,
	`extractor` text,
	`verified_by` text,
	`extracted_at` text,
	`superseded` integer DEFAULT 0,
	FOREIGN KEY (`doc_id`) REFERENCES `documents`(`doc_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `ix_cells_doc` ON `cells` (`doc_id`,`page_no`,`table_id`);--> statement-breakpoint
CREATE TABLE `decisions` (
	`decision_id` text PRIMARY KEY NOT NULL,
	`meeting_name` text,
	`meeting_date` text,
	`presented_data` text,
	`decided` text,
	`stalled_item_resolved` integer,
	`participants` text,
	`url` text,
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE `doc_series` (
	`doc_id` text,
	`table_id` text,
	`page_no` integer,
	`row_key` text,
	`label` text,
	`fiscal_year` integer,
	`value` real,
	`n_cells` integer,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_ds` ON `doc_series` (`doc_id`,`table_id`,`row_key`);--> statement-breakpoint
CREATE TABLE `doc_series_meta` (
	`doc_id` text,
	`table_id` text,
	`row_key` text,
	`label` text,
	`page_no` integer,
	`n_years` integer,
	`y_from` integer,
	`y_to` integer,
	`unit` text,
	`v_min` real,
	`v_max` real,
	`doc_title` text,
	`publisher` text,
	`url` text,
	`license` text,
	`n_warnings` integer
);
--> statement-breakpoint
CREATE INDEX `ix_dsm` ON `doc_series_meta` (`n_years`);--> statement-breakpoint
CREATE TABLE `documents` (
	`doc_id` text PRIMARY KEY NOT NULL,
	`title` text,
	`publisher` text,
	`url` text,
	`local_path` text,
	`doc_sha256` text,
	`n_pages` integer,
	`fiscal_year` integer,
	`license` text,
	`fetched_at` text
);
--> statement-breakpoint
CREATE TABLE `effort_year` (
	`year` integer,
	`n` integer,
	`species_n` integer,
	`mesh_n` integer,
	`n_inat` integer,
	`n_gbif` integer
);
--> statement-breakpoint
CREATE TABLE `event_observers` (
	`event_id` text,
	`observer_id` text,
	`part` text
);
--> statement-breakpoint
CREATE TABLE `events` (
	`event_id` text PRIMARY KEY NOT NULL,
	`site_id` text,
	`event_date` text,
	`event_time` text,
	`protocol_id` text,
	`protocol_version` text,
	`weather` text,
	`precip_24h_mm` real,
	`water_temp_c` real,
	`photo_count` integer,
	`gps_offset_m` real,
	`is_backfilled` integer DEFAULT 0,
	`is_rain_triggered` integer DEFAULT 0,
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE `extraction_log` (
	`ts` text,
	`doc_id` text,
	`page_no` integer,
	`table_id` text,
	`role` text,
	`attempt` integer,
	`verdict` text,
	`failures` text,
	`note` text
);
--> statement-breakpoint
CREATE TABLE `ias_species` (
	`ias_category` text,
	`binom` text,
	`name_ja` text,
	`taxon_group` text,
	`en_name` text,
	`n` integer,
	`mesh_n` integer,
	`y_from` integer,
	`y_to` integer,
	`n_since_2020` integer
);
--> statement-breakpoint
CREATE INDEX `ix_ias` ON `ias_species` (`n`);--> statement-breakpoint
CREATE TABLE `instruments` (
	`instrument_id` text PRIMARY KEY NOT NULL,
	`kind` text,
	`model` text,
	`calibrated_on` text,
	`calibration_note` text,
	`uncalibrated_flag` integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE `interventions` (
	`intervention_id` text PRIMARY KEY NOT NULL,
	`site_id` text,
	`kind` text,
	`parcel` text,
	`quantity` real,
	`quantity_unit` text,
	`started_on` text,
	`finished_on` text,
	`operator` text,
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE `landuse_change` (
	`watershed_id` text,
	`landuse_name` text,
	`km2_2006` real,
	`km2_2016` real,
	`delta_km2` real
);
--> statement-breakpoint
CREATE INDEX `ix_lc` ON `landuse_change` (`watershed_id`);--> statement-breakpoint
CREATE TABLE `landuse_watershed` (
	`watershed_id` text,
	`year` integer,
	`landuse_code` text,
	`landuse_name` text,
	`n_cells` integer,
	`area_km2` real
);
--> statement-breakpoint
CREATE INDEX `ix_lw` ON `landuse_watershed` (`watershed_id`,`year`);--> statement-breakpoint
CREATE TABLE `meas_clim` (
	`variable` text,
	`month` integer,
	`n` integer,
	`avg` real,
	`min` real,
	`max` real,
	`unit` text
);
--> statement-breakpoint
CREATE TABLE `meas_daily` (
	`site_id` text,
	`variable` text,
	`d` text,
	`value` real,
	`n_raw` integer,
	`n_censored` integer,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_md_site` ON `meas_daily` (`site_id`,`variable`,`d`);--> statement-breakpoint
CREATE INDEX `ix_md` ON `meas_daily` (`variable`,`site_id`,`d`);--> statement-breakpoint
CREATE TABLE `meas_month` (
	`site_id` text,
	`variable` text,
	`ym` text,
	`year` integer,
	`month` integer,
	`n` integer,
	`avg` real,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_mm_site` ON `meas_month` (`site_id`,`variable`,`ym`);--> statement-breakpoint
CREATE INDEX `ix_mm` ON `meas_month` (`variable`,`ym`);--> statement-breakpoint
CREATE TABLE `meas_year` (
	`site_id` text,
	`variable` text,
	`kind` text,
	`year` integer,
	`n` integer,
	`avg` real,
	`min` real,
	`max` real,
	`n_censored` integer,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_my_site` ON `meas_year` (`site_id`,`variable`,`kind`,`year`);--> statement-breakpoint
CREATE INDEX `ix_my` ON `meas_year` (`variable`,`kind`,`year`);--> statement-breakpoint
CREATE TABLE `measurements` (
	`measurement_id` text PRIMARY KEY NOT NULL,
	`event_id` text,
	`site_id` text,
	`measured_on` text,
	`variable` text,
	`variable_en` text,
	`value` real,
	`value_raw` text,
	`unit` text,
	`method` text,
	`instrument_id` text,
	`detection_flag` text,
	`quality_stage` text DEFAULT '暫定',
	`verified_by` text,
	`verified_on` text,
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE INDEX `ix_meas_site` ON `measurements` (`site_id`,`variable`,`measured_on`);--> statement-breakpoint
CREATE TABLE `mesh_all` (
	`mlat` integer,
	`mlon` integer,
	`n` integer,
	`rl_n` integer,
	`y_from` integer,
	`y_to` integer
);
--> statement-breakpoint
CREATE TABLE `mesh_species` (
	`mlat` integer,
	`mlon` integer,
	`species_n` integer,
	`rl_species_n` integer
);
--> statement-breakpoint
CREATE TABLE `mesh_year` (
	`mlat` integer,
	`mlon` integer,
	`year` integer,
	`n` integer,
	`species_n` integer,
	`rl_n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_my2` ON `mesh_year` (`year`);--> statement-breakpoint
CREATE TABLE `notes` (
	`note_id` text,
	`doc_id` text,
	`table_ids` text,
	`kind` text,
	`text` text,
	`page` integer,
	`blocks_timeseries` integer,
	`reason` text
);
--> statement-breakpoint
CREATE TABLE `observers` (
	`observer_id` text PRIMARY KEY NOT NULL,
	`display_name` text,
	`role` text,
	`org` text,
	`is_synthetic` integer DEFAULT 1
);
--> statement-breakpoint
CREATE TABLE `org_group_year` (
	`year` integer,
	`taxon_group` text,
	`source_id` text,
	`n` integer,
	`species_n` integer,
	`mesh_n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_ogy` ON `org_group_year` (`year`);--> statement-breakpoint
CREATE TABLE `org_norm` (
	`record_id` text,
	`source_id` text,
	`yr` integer,
	`mo` integer,
	`binom` text,
	`scientific_name` text,
	`vernacular_name` text,
	`rank_l` text,
	`cls` text,
	`kdm` text,
	`phy` text,
	`ord` text,
	`family` text,
	`lat` real,
	`lon` real,
	`mlat` integer,
	`mlon` integer,
	`red_list_category` text,
	`license_class` text,
	`is_alien` integer,
	`taxon_group` text
);
--> statement-breakpoint
CREATE INDEX `ix_on_yr` ON `org_norm` (`yr`);--> statement-breakpoint
CREATE INDEX `ix_on_mesh` ON `org_norm` (`mlat`,`mlon`);--> statement-breakpoint
CREATE INDEX `ix_on_grp` ON `org_norm` (`taxon_group`,`yr`);--> statement-breakpoint
CREATE INDEX `ix_on_binom` ON `org_norm` (`binom`,`yr`);--> statement-breakpoint
CREATE TABLE `org_watershed` (
	`watershed_id` text,
	`n` integer,
	`alien_n` integer,
	`redlist_n` integer,
	`y_from` integer,
	`y_to` integer
);
--> statement-breakpoint
CREATE INDEX `ix_ow` ON `org_watershed` (`watershed_id`);--> statement-breakpoint
CREATE TABLE `org_watershed_year` (
	`watershed_id` text,
	`year` integer,
	`n` integer,
	`species_n` integer,
	`alien_n` integer,
	`redlist_n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_owy` ON `org_watershed_year` (`watershed_id`,`year`);--> statement-breakpoint
CREATE TABLE `organism_records` (
	`record_id` text PRIMARY KEY NOT NULL,
	`event_id` text,
	`site_id` text,
	`observed_on` text,
	`scientific_name` text,
	`vernacular_name` text,
	`taxon_rank` text,
	`kingdom` text,
	`phylum` text,
	`class` text,
	`order` text,
	`family` text,
	`genus` text,
	`taxon_key` text,
	`individual_count` real,
	`density` real,
	`density_unit` text,
	`basis_of_record` text,
	`identified_by` text,
	`identification_basis` text,
	`identification_confidence` real,
	`lat` real,
	`lon` real,
	`coordinate_uncertainty_m` real,
	`red_list_category` text,
	`is_alien` integer DEFAULT 0,
	`quality_stage` text DEFAULT '暫定',
	`publication_scope` text DEFAULT '限定共有',
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0,
	`record_license` text,
	`license_class` text,
	`commercial_ok` integer
);
--> statement-breakpoint
CREATE INDEX `ix_org_license_class` ON `organism_records` (`license_class`);--> statement-breakpoint
CREATE INDEX `ix_org_name` ON `organism_records` (`scientific_name`);--> statement-breakpoint
CREATE TABLE `protocols` (
	`protocol_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`version` text,
	`domain` text,
	`steps_json` text,
	`source_id` text,
	`url` text
);
--> statement-breakpoint
CREATE TABLE `quality_monthly` (
	`ym` text,
	`submitted` integer,
	`verified` integer,
	`published` integer,
	`returned` integer
);
--> statement-breakpoint
CREATE TABLE `quality_transitions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`target_table` text,
	`target_id` text,
	`from_stage` text,
	`to_stage` text,
	`actor` text,
	`occurred_at` text,
	`note` text
);
--> statement-breakpoint
CREATE TABLE `rain_daily` (
	`d` text,
	`mm` real,
	`n_hours` integer
);
--> statement-breakpoint
CREATE INDEX `ix_rain` ON `rain_daily` (`d`);--> statement-breakpoint
CREATE TABLE `redlist_assessments` (
	`assessment_id` text PRIMARY KEY NOT NULL,
	`list_name` text NOT NULL,
	`list_year` integer NOT NULL,
	`taxon_group_ja` text,
	`taxon_subgroup_ja` text,
	`family_ja` text,
	`vernacular_name_ja` text,
	`scientific_name` text,
	`category_code` text,
	`category_ja` text,
	`category_prev_ja` text,
	`national_category_ja` text,
	`note_ja` text,
	`taxon_id` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE INDEX `idx_rla_group` ON `redlist_assessments` (`taxon_group_ja`);--> statement-breakpoint
CREATE INDEX `idx_rla_vname` ON `redlist_assessments` (`vernacular_name_ja`);--> statement-breakpoint
CREATE INDEX `idx_rla_year` ON `redlist_assessments` (`list_year`);--> statement-breakpoint
CREATE TABLE `redlist_change` (
	`assessment_id` text,
	`list_name` text,
	`list_year` integer,
	`taxon_group_ja` text,
	`taxon_subgroup_ja` text,
	`family_ja` text,
	`vernacular_name_ja` text,
	`scientific_name` text,
	`national_category_ja` text,
	`prev_label` text,
	`prev_code` text,
	`prev_rank` integer,
	`cur_label` text,
	`cur_code` text,
	`cur_rank` integer,
	`direction` text
);
--> statement-breakpoint
CREATE INDEX `ix_rc` ON `redlist_change` (`list_year`,`direction`);--> statement-breakpoint
CREATE TABLE `redlist_map` (
	`raw` text PRIMARY KEY NOT NULL,
	`label` text,
	`code` text,
	`rank` integer
);
--> statement-breakpoint
CREATE TABLE `_seed_state` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text,
	`updated_at` text
);
--> statement-breakpoint
CREATE TABLE `sensor_daily` (
	`site_id` text,
	`datastream` text,
	`d` text,
	`n` integer,
	`avg` real,
	`min` real,
	`max` real,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_sd` ON `sensor_daily` (`datastream`,`d`);--> statement-breakpoint
CREATE TABLE `sensor_hour_month` (
	`datastream` text,
	`month` integer,
	`hour` integer,
	`n` integer,
	`avg` real,
	`max` real
);
--> statement-breakpoint
CREATE TABLE `sensor_timeseries` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`site_id` text,
	`datastream` text,
	`phenomenon_time` text,
	`result` real,
	`unit` text,
	`instrument_id` text,
	`source_id` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE INDEX `ix_ts` ON `sensor_timeseries` (`site_id`,`datastream`,`phenomenon_time`);--> statement-breakpoint
CREATE TABLE `site_var` (
	`site_id` text,
	`variable` text,
	`kind` text,
	`n` integer,
	`y_from` integer,
	`y_to` integer,
	`avg` real,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_sv_var` ON `site_var` (`variable`);--> statement-breakpoint
CREATE INDEX `ix_sv` ON `site_var` (`site_id`);--> statement-breakpoint
CREATE TABLE `sites` (
	`site_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`name_en` text,
	`watershed` text,
	`zone` integer,
	`lat` real,
	`lon` real,
	`elevation_m` real,
	`geohash` text,
	`municipality` text,
	`muni_code` text,
	`treatment` text,
	`established_on` text,
	`operator` text,
	`source_id` text,
	`source_ref` text,
	`is_synthetic` integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE `source_registry` (
	`source_id` text PRIMARY KEY NOT NULL,
	`name` text,
	`publisher` text,
	`url` text,
	`category` text,
	`access_method` text,
	`format` text,
	`license` text,
	`redistributable` integer,
	`fetched_at` text,
	`record_count` integer,
	`notes` text
);
--> statement-breakpoint
CREATE TABLE `species2` (
	`binom` text,
	`taxon_group` text,
	`cls` text,
	`family` text,
	`en_name` text,
	`red_list_category` text,
	`n` integer,
	`y_from` integer,
	`y_to` integer,
	`n_years` integer,
	`mesh_n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_sp2_g` ON `species2` (`taxon_group`,`n`);--> statement-breakpoint
CREATE INDEX `ix_sp2` ON `species2` (`n`);--> statement-breakpoint
CREATE TABLE `species_mesh_year` (
	`binom` text,
	`year` integer,
	`mlat` integer,
	`mlon` integer,
	`n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_smy` ON `species_mesh_year` (`binom`,`year`);--> statement-breakpoint
CREATE TABLE `species_month` (
	`binom` text,
	`month` integer,
	`n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_spm` ON `species_month` (`binom`);--> statement-breakpoint
CREATE TABLE `species_year2` (
	`binom` text,
	`year` integer,
	`n` integer,
	`mesh_n` integer
);
--> statement-breakpoint
CREATE INDEX `ix_sy2` ON `species_year2` (`binom`,`year`);--> statement-breakpoint
CREATE TABLE `taxa` (
	`taxon_id` text PRIMARY KEY NOT NULL,
	`scientific_name` text,
	`vernacular_name_ja` text,
	`taxon_group_ja` text,
	`kingdom` text,
	`phylum` text,
	`class` text,
	`order` text,
	`family` text,
	`genus` text,
	`gbif_taxon_key` text,
	`gbif_match_type` text,
	`redlist_kanagawa` text,
	`redlist_national` text,
	`ias_category` text,
	`source_id` text,
	`source_ref` text
);
--> statement-breakpoint
CREATE TABLE `var_catalog` (
	`variable` text,
	`unit` text,
	`n` integer,
	`n_sites` integer,
	`y_from` integer,
	`y_to` integer,
	`n_daily` integer,
	`n_annual` integer,
	`n_censored` integer
);
--> statement-breakpoint
CREATE TABLE `vocab_areas` (
	`doc_id` text,
	`name` text,
	`definition` text,
	`found_definition` integer,
	`pages` text
);
--> statement-breakpoint
CREATE TABLE `vocab_eras` (
	`doc_id` text,
	`literal` text,
	`pages` text
);
--> statement-breakpoint
CREATE TABLE `vocab_indicators` (
	`doc_id` text,
	`name` text,
	`unit` text,
	`method` text,
	`pages` text
);
--> statement-breakpoint
CREATE TABLE `vocab_units` (
	`doc_id` text,
	`literal` text,
	`quantity` text,
	`pages` text
);
--> statement-breakpoint
CREATE TABLE `watershed_meta` (
	`watershed_id` text PRIMARY KEY NOT NULL,
	`water_system_code` text,
	`water_system_name` text,
	`water_system_category` text,
	`main_rivers` text,
	`area_km2` real,
	`centroid_lat` real,
	`centroid_lon` real,
	`data_year` integer,
	`source_ref` text
);
--> statement-breakpoint
CREATE TABLE `watershed_rollup` (
	`watershed_id` text,
	`water_system_name` text,
	`area_km2` real,
	`centroid_lat` real,
	`centroid_lon` real,
	`org_n` integer,
	`org_alien_n` integer,
	`org_redlist_n` integer,
	`site_n` integer,
	`site_var_n` integer,
	`built_km2_2016` real,
	`built_km2_2006` real,
	`forest_km2_2016` real,
	`forest_km2_2006` real,
	`paddy_km2_2016` real,
	`paddy_km2_2006` real
);
--> statement-breakpoint
CREATE INDEX `ix_wr` ON `watershed_rollup` (`watershed_id`);--> statement-breakpoint
CREATE TABLE `zone_clim` (
	`zone` integer,
	`variable` text,
	`month` integer,
	`n_sites` integer,
	`n` integer,
	`avg` real,
	`unit` text
);
--> statement-breakpoint
CREATE TABLE `zone_year` (
	`zone` integer,
	`variable` text,
	`kind` text,
	`year` integer,
	`n_sites` integer,
	`n` integer,
	`avg` real,
	`unit` text
);
--> statement-breakpoint
CREATE INDEX `ix_zy` ON `zone_year` (`variable`,`kind`,`year`);