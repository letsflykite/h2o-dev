setwd(normalizePath(dirname(R.utils::commandArgs(asValues=TRUE)$"f")))
source('../h2o-runit.R')

test.kmsplit.golden <- function(conn) {
  library(flexclust)
  Log.info("Importing ozone.csv data...\n")
  ozoneR <- read.csv(locate("smalldata/glm_test/ozone.csv"), header = TRUE)
  ozoneH2O <- h2o.uploadFile(conn, locate("smalldata/glm_test/ozone.csv"))
  
  Log.info("Split into test and training sets\n")
  trainIdx <- sort(sample(nrow(ozoneR), round(0.75*nrow(ozoneR))))
  testIdx <- sort(setdiff(1:nrow(ozoneR), trainIdx))
  trainR <- ozoneR[trainIdx,]; testR <- ozoneR[testIdx,]
  trainH2O <- ozoneH2O[trainIdx,]; testH2O <- ozoneH2O[testIdx,]
  startIdx <- sort(sample(1:nrow(trainR), 3))
  
  Log.info("Initial cluster centers:"); print(trainR[startIdx,])
  # fitR <- kmeans(trainR, centers = trainR[startIdx,], iter.max = 1000, algorithm = "Lloyd")
  fitR <- kcca(trainR, k = as.matrix(trainR[startIdx,], family = kccaFamily("kmeans"), control = list(iter.max = 1000)))
  fitH2O <- h2o.kmeans(trainH2O, init = trainH2O[startIdx,], standardize = FALSE)
  
  Log.info("R Final Clusters:"); print(fitR@centers)
  Log.info("H2O Final Clusters:"); print(fitH2O@model$centers)
  expect_equivalent(as.matrix(fitH2O@model$centers), fitR@centers)
  
  Log.info("Compare Predicted Classes on Test Data between R and H2O\n")
  classR <- predict(fitR, testR)
  # FIXME: predict directly on sliced H2O frame breaks
  # classH2O <- predict(fitH2O, testH2O)
  classH2O <- predict(fitH2O, as.h2o(conn, testR))
  expect_equivalent(as.numeric(as.matrix(classH2O))+1, classR)
  
  testEnd()
}

doTest("KMeans Test: Golden Kmeans - Ozone Test/Train Split without Standardization", test.kmsplit.golden)