#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 3) {
  stop("usage: Rscript forecast.R input.csv output.csv manifest.csv", call. = FALSE)
}

input_path <- args[[1]]
output_path <- args[[2]]
manifest_path <- args[[3]]
source_data <- read.csv(input_path, stringsAsFactors = FALSE, check.names = FALSE)
required <- c("region", "index", "timestamp_source", "demand_mw")
if (!all(required %in% names(source_data))) {
  stop("canonical input is missing required columns", call. = FALSE)
}
manifest <- read.csv(manifest_path, stringsAsFactors = FALSE, check.names = FALSE)
manifest_required <- c("fold_id", "split", "region", "origin_index", "horizon")
if (!all(manifest_required %in% names(manifest))) {
  stop("origin manifest is missing required columns", call. = FALSE)
}

origins <- list()
output <- list()
for (region in sort(unique(source_data$region))) {
  series <- source_data[source_data$region == region, ]
  series <- series[order(series$index), ]
  horizon <- 48
  region_folds <- manifest[manifest$region == region, ]
  for (fold_index in seq_len(nrow(region_folds))) {
    fold <- region_folds[fold_index, ]
    origin <- as.integer(fold$origin_index)
    horizon <- as.integer(fold$horizon)
    if (origin < 336 || origin + horizon > nrow(series)) {
      stop(sprintf("origin outside series for %s: %d", region, origin), call. = FALSE)
    }
    train <- series$demand_mw[seq_len(origin)]
    test <- series[(origin + 1):(origin + horizon), ]
    fit <- tryCatch(
      stats::arima(train, order = c(1, 0, 0), include.mean = TRUE),
      error = function(error) NULL
    )
    if (is.null(fit)) {
      next
    }
    predictions <- as.numeric(stats::predict(fit, n.ahead = horizon)$pred)
    for (lead in seq_len(horizon)) {
      output[[length(output) + 1]] <- data.frame(
        market = "NEM",
        region = region,
        origin_index = origin,
        fold_id = fold$fold_id,
        split = fold$split,
        horizon = lead,
        target_time_source = test$timestamp_source[[lead]],
        actual_mw = test$demand_mw[[lead]],
        forecast_mw = predictions[[lead]],
        model_id = "r_arima_100",
        model_version = paste0("R-", R.version$major, ".", R.version$minor),
        stringsAsFactors = FALSE
      )
    }
  }
}
if (length(output) == 0) {
  stop("R produced no valid fits", call. = FALSE)
}
result <- do.call(rbind, output)
write.csv(result, output_path, row.names = FALSE, na = "")
cat(sprintf("rows=%d regions=%d\n", nrow(result), length(unique(result$region))))
