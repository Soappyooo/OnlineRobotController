import { describe, expect, it } from "vitest";

import { Dashboard } from "./Dashboard";

describe("dashboard smoke", () => {
  it("exports dashboard component", () => {
    expect(typeof Dashboard).toBe("function");
  });
});
