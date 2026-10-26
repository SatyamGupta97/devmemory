import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createMemory,
  deleteMemory,
  listMemories,
  updateMemory,
} from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubFetch(response: Response | (() => never)) {
  const mock = vi.fn(
    response instanceof Response ? () => Promise.resolve(response) : response,
  );
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("listMemories", () => {
  it("calls the collection endpoint with no query when unfiltered", async () => {
    const fetchMock = stubFetch(jsonResponse([]));

    await listMemories();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/memories",
      expect.anything(),
    );
  });

  it("sends project and category as query parameters", async () => {
    const fetchMock = stubFetch(jsonResponse([]));

    await listMemories({ project: "payments-api", category: "decision" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/memories?project=payments-api&category=decision",
      expect.anything(),
    );
  });
});

describe("error handling", () => {
  it("reports an unreachable server distinctly from an HTTP error", async () => {
    // fetch rejects only when no response was produced at all.
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });

    await expect(listMemories()).rejects.toThrow(ApiError);
    await expect(listMemories()).rejects.toThrow(/Is the backend running/);
  });

  it("turns a validation response into a readable field message", async () => {
    stubFetch(
      jsonResponse(
        {
          detail: [
            {
              type: "string_too_short",
              loc: ["body", "content"],
              msg: "String should have at least 1 character",
            },
          ],
        },
        422,
      ),
    );

    await expect(
      createMemory({
        content: "",
        category: "decision",
        source: "x",
        project: "y",
      }),
    ).rejects.toThrow("content: String should have at least 1 character");
  });

  it("uses the string detail from a 409 response", async () => {
    stubFetch(jsonResponse({ detail: "Memory 'a' is referenced." }, 409));

    const error = await deleteMemory("a").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("Memory 'a' is referenced.");
  });

  it("falls back to the status when the body is not JSON", async () => {
    stubFetch(new Response("<html>gateway error</html>", { status: 502 }));

    await expect(listMemories()).rejects.toThrow("Request failed with status 502");
  });

  it("keeps the status code on the thrown error", async () => {
    stubFetch(jsonResponse({ detail: "Memory 'x' not found" }, 404));

    const error = await updateMemory("x", { content: "y" }).catch(
      (caught: unknown) => caught,
    );

    expect((error as ApiError).status).toBe(404);
  });
});

describe("deleteMemory", () => {
  it("resolves on 204 without trying to parse a body", async () => {
    // A 204 has no body; calling .json() on it would throw.
    stubFetch(new Response(null, { status: 204 }));

    await expect(deleteMemory("abc")).resolves.toBeUndefined();
  });
});
