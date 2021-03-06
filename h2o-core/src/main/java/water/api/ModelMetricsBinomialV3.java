package water.api;

import hex.ModelMetricsBinomial;

public class ModelMetricsBinomialV3 extends ModelMetricsBase<ModelMetricsBinomial, ModelMetricsBinomialV3> {
  @API(help="The Mean Squared Error of the prediction for this scoring run.", direction=API.Direction.OUTPUT)
  public double mse;

  @API(help="The AUC object for this scoring run.", direction=API.Direction.OUTPUT)
  public AUCBase auc;

  @API(help="The ConfusionMatrix object for this scoring run.", direction=API.Direction.OUTPUT)
  public ConfusionMatrixBase cm;

  @Override public ModelMetricsBinomialV3 fillFromImpl(ModelMetricsBinomial modelMetrics) {
    super.fillFromImpl(modelMetrics);
    this.mse = modelMetrics._mse;

    if (null != modelMetrics._aucdata)
      this.auc = (AUCBase)Schema.schema(this.getSchemaVersion(), modelMetrics._aucdata).fillFromImpl(modelMetrics._aucdata);

    if (null != modelMetrics._cm)
      this.cm = (ConfusionMatrixBase)Schema.schema(this.getSchemaVersion(), modelMetrics._cm).fillFromImpl(modelMetrics._cm);

    return this;
  }
}
