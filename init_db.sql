-- ============================================================
-- init_db.sql — New Era Games database schema (Volume Storage)
-- Executed on app startup to ensure all tables exist
-- ============================================================

-- 1. users
CREATE TABLE IF NOT EXISTS `users` (
    `id`         INT          NOT NULL AUTO_INCREMENT,
    `username`   VARCHAR(50)  NOT NULL,
    `email`      VARCHAR(100) NOT NULL,
    `password`   VARCHAR(255) NOT NULL,
    `pic`        VARCHAR(255) NULL,   -- Path to avatar image in static/uploads
    `role`       ENUM('standard','developer','admin') NOT NULL DEFAULT 'standard',
    `slug`       VARCHAR(60)  NULL,   -- URL-friendly username
    `created_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_username` (`username`),
    UNIQUE KEY `uq_email`    (`email`),
    UNIQUE KEY `uq_slug`     (`slug`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. games
CREATE TABLE IF NOT EXISTS `games` (
    `id`          INT          NOT NULL AUTO_INCREMENT,
    `title`       VARCHAR(100) NOT NULL,
    `description` TEXT         NOT NULL,
    `categories`  VARCHAR(100) NOT NULL,
    `cover`       VARCHAR(255) NOT NULL, -- Path to cover image in static/uploads
    `game_file`   VARCHAR(255) NULL,     -- Path to actual game in static/uploads
    `slug`        VARCHAR(120) NULL,     -- URL-friendly title
    `creator_id`  INT          NULL,
    `created_at`  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_game_slug` (`slug`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. comments
CREATE TABLE IF NOT EXISTS `comments` (
    `id`         INT      NOT NULL AUTO_INCREMENT,
    `game_id`    INT      NOT NULL,
    `user_id`    INT      NOT NULL,
    `content`    TEXT     NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. comment_likes
CREATE TABLE IF NOT EXISTS `comment_likes` (
    `id`         INT      NOT NULL AUTO_INCREMENT,
    `comment_id` INT      NOT NULL,
    `user_id`    INT      NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_like` (`comment_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. comment_replies
CREATE TABLE IF NOT EXISTS `comment_replies` (
    `id`         INT      NOT NULL AUTO_INCREMENT,
    `comment_id` INT      NOT NULL,
    `user_id`    INT      NOT NULL,
    `content`    TEXT     NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. follows (user -> user)
CREATE TABLE IF NOT EXISTS `follows` (
    `follower_id` INT NOT NULL,
    `followed_id` INT NOT NULL,
    `created_at`  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`follower_id`, `followed_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. favorites_games (user -> game)
CREATE TABLE IF NOT EXISTS `favorites_games` (
    `user_id`    INT NOT NULL,
    `game_id`    INT NOT NULL,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `game_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. favorites_developers (user -> developer)
CREATE TABLE IF NOT EXISTS `favorites_developers` (
    `user_id`      INT NOT NULL,
    `developer_id` INT NOT NULL,
    `created_at`   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`user_id`, `developer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
