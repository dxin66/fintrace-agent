package com.financial.workflow;

import org.springframework.context.annotation.*;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;
import org.springframework.security.web.csrf.HttpSessionCsrfTokenRepository;

@Configuration
public class SecurityConfig {

  @Bean
  BCryptPasswordEncoder passwordEncoder() {
    return new BCryptPasswordEncoder();
  }

  @Bean
  SecurityFilterChain security(HttpSecurity http) throws Exception {
    return http
      .csrf(c ->
        c
          .csrfTokenRepository(new HttpSessionCsrfTokenRepository())
          .csrfTokenRequestHandler(new CsrfTokenRequestAttributeHandler())
      )
      .authorizeHttpRequests(a ->
        a
          .requestMatchers(
            "/",
            "/index.html",
            "/assets/**",
            "/favicon.svg",
            "/api/auth/csrf",
            "/api/auth/login",
            "/api/auth/register",
            "/api/health",
            "/error"
          )
          .permitAll()
          .anyRequest()
          .authenticated()
      )
      .exceptionHandling(e ->
        e
          .authenticationEntryPoint((req, res, ex) -> {
            res.setStatus(401);
            res.setContentType("application/json;charset=UTF-8");
            res.getWriter().write("{\"message\":\"请先登录\"}");
          })
          .accessDeniedHandler((req, res, ex) -> {
            res.setStatus(403);
            res.setContentType("application/json;charset=UTF-8");
            res
              .getWriter()
              .write("{\"message\":\"请求无权限或安全令牌失效，请刷新页面\"}");
          })
      )
      .headers(h ->
        h
          .frameOptions(f -> f.sameOrigin())
          .contentSecurityPolicy(c ->
            c.policyDirectives(
              "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'"
            )
          )
      )
      .build();
  }
}
