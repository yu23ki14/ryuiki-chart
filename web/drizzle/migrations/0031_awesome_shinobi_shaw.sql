CREATE TABLE `document_article_places` (
	`article_id` text NOT NULL,
	`place_raw` text NOT NULL,
	`place_type` text,
	`place_id` text,
	`match_method` text,
	`confidence` real,
	PRIMARY KEY(`article_id`, `place_raw`),
	FOREIGN KEY (`article_id`) REFERENCES `document_articles`(`article_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `ix_document_article_places_place` ON `document_article_places` (`place_id`);--> statement-breakpoint
CREATE TABLE `document_article_topics` (
	`article_id` text NOT NULL,
	`topic_id` text NOT NULL,
	`extractor` text,
	`confidence` real,
	PRIMARY KEY(`article_id`, `topic_id`),
	FOREIGN KEY (`article_id`) REFERENCES `document_articles`(`article_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `document_articles` (
	`article_id` text PRIMARY KEY NOT NULL,
	`issue_id` text NOT NULL,
	`doc_id` text NOT NULL,
	`source_id` text,
	`region_id` text,
	`kind` text,
	`page_from` integer,
	`page_to` integer,
	`issue_page_from` integer,
	`issue_page_to` integer,
	`title` text,
	`section` text,
	`body_text` text,
	`body_sha256` text,
	`event_dates` text,
	`doc_sha256` text,
	`extractor` text,
	`confidence` real,
	`verified_by` text,
	`unreadable_reason` text,
	`extracted_at` text,
	FOREIGN KEY (`issue_id`) REFERENCES `periodical_issues`(`issue_id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`doc_id`) REFERENCES `documents`(`doc_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `ix_document_articles_issue` ON `document_articles` (`issue_id`);--> statement-breakpoint
CREATE INDEX `ix_document_articles_doc` ON `document_articles` (`doc_id`,`page_from`);--> statement-breakpoint
CREATE INDEX `ix_document_articles_source` ON `document_articles` (`source_id`);--> statement-breakpoint
CREATE TABLE `periodical_issue_files` (
	`doc_id` text PRIMARY KEY NOT NULL,
	`issue_id` text NOT NULL,
	`part_no` integer,
	`page_offset` integer,
	`link_text_raw` text,
	`download_url` text,
	FOREIGN KEY (`doc_id`) REFERENCES `documents`(`doc_id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`issue_id`) REFERENCES `periodical_issues`(`issue_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `ix_periodical_issue_files_issue` ON `periodical_issue_files` (`issue_id`);--> statement-breakpoint
CREATE TABLE `periodical_issues` (
	`issue_id` text PRIMARY KEY NOT NULL,
	`series_id` text,
	`source_id` text,
	`region_id` text,
	`kind` text,
	`year_month` text,
	`year_month_to` text,
	`fiscal_year` integer,
	`issued_on` text,
	`issued_on_raw` text,
	`label_raw` text,
	`listing_url` text,
	`headlines` text,
	`n_files` integer,
	`n_pages` integer,
	`note` text,
	FOREIGN KEY (`series_id`) REFERENCES `periodical_series`(`series_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `ix_periodical_issues_source` ON `periodical_issues` (`source_id`);--> statement-breakpoint
CREATE INDEX `ix_periodical_issues_ym` ON `periodical_issues` (`year_month`);--> statement-breakpoint
CREATE TABLE `periodical_series` (
	`series_id` text PRIMARY KEY NOT NULL,
	`source_id` text,
	`title` text,
	`publisher` text,
	`region_id` text,
	`listing_urls` text,
	`license` text,
	`agreement_note` text
);
