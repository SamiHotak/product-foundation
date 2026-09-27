"use client";

import { useCallback, useState } from "react";

import { errorMessage, fieldErrors } from "@/lib/api";
import type { Rule } from "@/lib/validation";

type Values = Record<string, string>;

type Options<V extends Values> = {
  initial: V;
  /** One rule per field (combine several with `rules(...)` from lib/validation.ts). */
  validate?: { [K in keyof V]?: Rule<V> };
  /**
   * Save. Throw (e.g. an ApiError from `unwrap`) to show the error:
   * field errors from the API (422) appear under the fields, anything else above the form.
   * Return a field map from `mapError` to put other API errors under a field.
   */
  onSubmit: (values: V) => Promise<void> | void;
  mapError?: (err: unknown) => Partial<Record<keyof V, string>> | null;
};

/**
 * Form state with validation, for controlled inputs inside <Field>:
 *
 *   const form = useForm({
 *     initial: { name: "" },
 *     validate: { name: rules(required("Give it a name."), maxLength(80)) },
 *     onSubmit: async ({ name }) => { await unwrap(api.PATCH(..., { body: { name } })); },
 *   });
 *   <form {...form.formProps}>
 *     <Field label="Name" error={form.errors.name}>{(a) => <Input {...a} {...form.field("name")} />}</Field>
 *
 * Errors show after a field loses focus (not while typing the first time), and on submit.
 * After a failed submit they update on every key press. The first invalid field gets focus.
 */
export function useForm<V extends Values>({ initial, validate, onSubmit, mapError }: Options<V>) {
  const [values, setValues] = useState<V>(initial);
  const [errors, setErrors] = useState<Partial<Record<keyof V, string>>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [base, setBase] = useState<V>(initial);

  const check = useCallback(
    (name: keyof V, all: V): string | undefined => validate?.[name]?.(all[name] ?? "", all),
    [validate],
  );

  function setValue(name: keyof V, value: string) {
    const next = { ...values, [name]: value };
    setValues(next);
    if (submitted) setErrors((e) => ({ ...e, [name]: check(name, next) }));
  }

  function field(name: keyof V & string) {
    return {
      name,
      value: values[name] ?? "",
      onChange: (
        e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>,
      ) => setValue(name, e.target.value),
      onBlur: () => {
        const value = values[name] ?? "";
        // Don't complain about a field the person only tabbed through.
        if (value !== "" || submitted) setErrors((e) => ({ ...e, [name]: check(name, values) }));
      },
    };
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setSubmitted(true);
    setFormError(null);
    const found: Partial<Record<keyof V, string>> = {};
    for (const name of Object.keys(values) as (keyof V)[]) {
      const message = check(name, values);
      if (message) found[name] = message;
    }
    setErrors(found);
    const firstInvalid = Object.keys(found)[0];
    if (firstInvalid) {
      const el = form.elements.namedItem(firstInvalid);
      if (el instanceof HTMLElement) el.focus();
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(values);
    } catch (err) {
      const mapped = mapError?.(err) ?? null;
      const apiFields = fieldErrors(err) as Partial<Record<keyof V, string>>;
      const known = Object.fromEntries(
        Object.entries({ ...apiFields, ...mapped }).filter(([key]) => key in values),
      ) as Partial<Record<keyof V, string>>;
      if (Object.keys(known).length > 0) {
        setErrors(known);
        const el = form.elements.namedItem(Object.keys(known)[0]!);
        if (el instanceof HTMLElement) el.focus();
      } else {
        setFormError(errorMessage(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  /** Back to the start values, or to `next` (e.g. the saved values, so `dirty` is false). */
  function reset(next: V = base) {
    setBase(next);
    setValues(next);
    setErrors({});
    setFormError(null);
    setSubmitted(false);
  }

  const dirty = (Object.keys(values) as (keyof V)[]).some((key) => values[key] !== base[key]);

  return {
    values,
    errors,
    formError,
    submitting,
    dirty,
    field,
    setValue,
    reset,
    handleSubmit,
    /** Spread on <form>: submit handler + noValidate (we validate ourselves, with better text). */
    formProps: { onSubmit: handleSubmit, noValidate: true },
  };
}
