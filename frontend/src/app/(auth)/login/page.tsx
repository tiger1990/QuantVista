"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { TrendingUp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const schema = z.object({
  email: z.string().email("Enter a valid email."),
  password: z.string().min(1, "Enter your password."),
});
type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const { login } = useAuth();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues): Promise<void> {
    setFormError(null);
    try {
      await login(values.email, values.password);
    } catch (error: unknown) {
      setFormError(error instanceof Error ? error.message : "Sign in failed.");
    }
  }

  return (
    <Card>
      <CardHeader className="items-start gap-2">
        <div className="flex items-center gap-2 font-mono text-sm font-semibold tracking-tight">
          <TrendingUp className="size-4 text-primary" />
          QUANT<span className="text-muted-foreground">VISTA</span>
        </div>
        <CardTitle className="text-xl">Sign in</CardTitle>
        <CardDescription>Access your equity research workspace.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" aria-invalid={!!errors.email} {...register("email")} />
            {errors.email ? <p className="text-xs text-destructive">{errors.email.message}</p> : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!errors.password} {...register("password")} />
            {errors.password ? <p className="text-xs text-destructive">{errors.password.message}</p> : null}
          </div>
          {formError ? <p className="text-sm text-destructive">{formError}</p> : null}
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          No account?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Create one
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
