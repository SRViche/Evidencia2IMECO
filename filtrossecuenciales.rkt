
; funcionessecuenciales.rkt
; Aquí vamos a colocar las funciones sisisi
;
; Autores: Ivan Burrola, Alberto Lopez, Axel Lugo, Sebastian Viche
; Materia: Implementacion de metodos computacionales


;--------------------------------------------------------------------------------
#lang racket

(provide negative-sequential!
         grayscale-sequential!
         sepia-sequential!
         edge-sequential!
         gaussian-sequential!)


(define (negative-sequential! bytes-buf)
  (define len (bytes-length bytes-buf))
  (for ([i (in-range 0 len 4)])
    (bytes-set! bytes-buf (+ i 1) (- 255 (bytes-ref bytes-buf (+ i 1))))
    (bytes-set! bytes-buf (+ i 2) (- 255 (bytes-ref bytes-buf (+ i 2))))
    (bytes-set! bytes-buf (+ i 3) (- 255 (bytes-ref bytes-buf (+ i 3))))))

;; ==========================================
;; 2. ESCALA DE GRISES
;; ==========================================
(define (grayscale-sequential! bytes-buf)
  (define len (bytes-length bytes-buf))
  (for ([i (in-range 0 len 4)])
    (let* ([r (bytes-ref bytes-buf (+ i 1))]
           [g (bytes-ref bytes-buf (+ i 2))]
           [b (bytes-ref bytes-buf (+ i 3))]
           [lum (exact-round (+ (* 0.299 r) (* 0.587 g) (* 0.114 b)))])
      (bytes-set! bytes-buf (+ i 1) lum)
      (bytes-set! bytes-buf (+ i 2) lum)
      (bytes-set! bytes-buf (+ i 3) lum))))

;; ==========================================
;; 3. SEPIA
;; ==========================================
(define (sepia-sequential! bytes-buf)
  (define len (bytes-length bytes-buf))
  (for ([i (in-range 0 len 4)])
    (let* ([r (bytes-ref bytes-buf (+ i 1))]
           [g (bytes-ref bytes-buf (+ i 2))]
           [b (bytes-ref bytes-buf (+ i 3))]
           [new-r (exact-round (+ (* 0.393 r) (* 0.769 g) (* 0.189 b)))]
           [new-g (exact-round (+ (* 0.349 r) (* 0.686 g) (* 0.168 b)))]
           [new-b (exact-round (+ (* 0.272 r) (* 0.534 g) (* 0.131 b)))])
      (bytes-set! bytes-buf (+ i 1) (min 255 new-r))
      (bytes-set! bytes-buf (+ i 2) (min 255 new-g))
      (bytes-set! bytes-buf (+ i 3) (min 255 new-b)))))

;; ==========================================
;; HELPER PARA CONVOLUCIÓN
;; Convierte coordenadas (x,y) al índice base del pixel en el byte-string
;; ==========================================
(define (get-idx x y w)
  (* 4 (+ x (* y w))))

;; ==========================================
;; 4. EDGE DETECTION (Filtro Laplaciano 3x3)
;; ==========================================
(define (edge-sequential! bytes-buf w h)
  (define src (bytes-copy bytes-buf)) ; Buffer inmutable para lectura
  ;; La salida de edge detection usa bordes negros, igual que las versiones
  ;; recursiva y paralela; alpha se conserva para reconstruir la imagen.
  (for ([i (in-range (* w h))])
    (define base (* i 4))
    (bytes-set! bytes-buf base (bytes-ref src base))
    (bytes-set! bytes-buf (+ base 1) 0)
    (bytes-set! bytes-buf (+ base 2) 0)
    (bytes-set! bytes-buf (+ base 3) 0))
  ;; Iteramos desde 1 hasta w-1 / h-1 para ignorar los bordes extremos.
  (for* ([y (in-range 1 (- h 1))]
         [x (in-range 1 (- w 1))])
    (define idx (get-idx x y w))
    (for ([c (in-range 1 4)]) ; Iterar sobre R(1), G(2), B(3)
      (let ([val (+ (* 8  (bytes-ref src (+ (get-idx x y w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (- x 1) (- y 1) w) c)))
                    (* -1 (bytes-ref src (+ (get-idx x (- y 1) w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (+ x 1) (- y 1) w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (- x 1) y w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (+ x 1) y w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (- x 1) (+ y 1) w) c)))
                    (* -1 (bytes-ref src (+ (get-idx x (+ y 1) w) c)))
                    (* -1 (bytes-ref src (+ (get-idx (+ x 1) (+ y 1) w) c))))])
        (bytes-set! bytes-buf (+ idx c) (max 0 (min 255 val)))))))

;; ==========================================
;; 5. GAUSSIAN BLUR (Kernel 3x3)
;; ==========================================
(define (gaussian-sequential! bytes-buf w h)
  (define src (bytes-copy bytes-buf))
  (for* ([y (in-range 1 (- h 1))]
         [x (in-range 1 (- w 1))])
    (define idx (get-idx x y w))
    (for ([c (in-range 1 4)])
      (let ([val (+ (* 4 (bytes-ref src (+ (get-idx x y w) c)))
                    (* 2 (bytes-ref src (+ (get-idx x (- y 1) w) c)))
                    (* 2 (bytes-ref src (+ (get-idx x (+ y 1) w) c)))
                    (* 2 (bytes-ref src (+ (get-idx (- x 1) y w) c)))
                    (* 2 (bytes-ref src (+ (get-idx (+ x 1) y w) c)))
                    (* 1 (bytes-ref src (+ (get-idx (- x 1) (- y 1) w) c)))
                    (* 1 (bytes-ref src (+ (get-idx (+ x 1) (- y 1) w) c)))
                    (* 1 (bytes-ref src (+ (get-idx (- x 1) (+ y 1) w) c)))
                    (* 1 (bytes-ref src (+ (get-idx (+ x 1) (+ y 1) w) c))))])
        ;; Dividimos entre 16 porque es la suma de los pesos del Kernel
        (bytes-set! bytes-buf (+ idx c) (quotient val 16))))))
