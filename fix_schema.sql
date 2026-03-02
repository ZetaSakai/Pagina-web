ALTER TABLE games CHANGE COLUMN `creator-pic` `creator_pic` LONGBLOB NULL;
ALTER TABLE games CHANGE COLUMN `creator-name` `creator_name` VARCHAR(50) NULL;
ALTER TABLE games MODIFY COLUMN cover LONGBLOB NOT NULL;
