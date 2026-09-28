package com.financial.workflow;

import java.math.*;
import java.util.*;

public final class Calculator {

  private Calculator() {}

  public static Map<String, Object> calculate(
    String operation,
    String left,
    String right,
    String unit
  ) {
    BigDecimal a = new BigDecimal(left),
      b = new BigDecimal(right);
    if (
      a.precision() > 40 ||
      b.precision() > 40 ||
      Math.abs(a.scale()) > 20 ||
      Math.abs(b.scale()) > 20
    ) throw Support.bad("数值超出范围");
    BigDecimal result = switch (operation) {
      case "add" -> a.add(b);
      case "subtract" -> a.subtract(b);
      case "multiply" -> a.multiply(b);
      case "divide" -> a.divide(b, 8, RoundingMode.HALF_UP);
      case "growth_percent" -> a
        .subtract(b)
        .divide(b, 8, RoundingMode.HALF_UP)
        .multiply(BigDecimal.valueOf(100));
      default -> throw Support.bad("未知计算操作");
    };
    return Map.of(
      "operation",
      operation,
      "left",
      left,
      "right",
      right,
      "unit",
      operation.equals("growth_percent") ? "%" : unit,
      "input_unit",
      unit,
      "result",
      result.stripTrailingZeros().toPlainString(),
      "formula",
      operation.equals("growth_percent") ? "(left-right)/right*100" : operation
    );
  }
}
